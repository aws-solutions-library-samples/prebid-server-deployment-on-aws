// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// ALB Entry Deployment — creates all resources for user's own CDN path (no CloudFront)
// Ported from alb_entry_deployment.py

import { Aspects, CfnCondition, CfnOutput } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import { ConditionAspect } from "../shared/condition-aspect";
import { StackParams } from "./stack-cfn-parameters";
import { VpcConstruct } from "./vpc-construct";
import { ContainerImageConstruct } from "./container-image-construct";
import { ArtifactsManager } from "./artifacts-construct";
import { EfsConstruct } from "./efs-construct";
import { EcsTaskConstruct } from "./ecs-task-construct";
import { EcsServiceConstruct } from "./ecs-service-construct";
import { AlbAccessLogsConstruct } from "./alb-access-logs-construct";
import { DataSyncMonitoring, DataSyncTask, EfsCleanup } from "./datasync-constructs";
import { GlueEtl } from "./glue-constructs";
import { CloudwatchMetricsConstruct, BaseCloudwatchDashboard } from "./cloudwatch-constructs";
import { CloudwatchAlarms } from "./cloudwatch-alarms-construct";import { CacheConstruct } from "./cache-construct";
import * as constants from "../shared/stack-constants";

export interface ALBEntryDeploymentProps {
  stackParams: StackParams;
  deployAlbHttpsCondition: CfnCondition;
  artifactsConstruct: ArtifactsManager;
  datasyncMonitor: DataSyncMonitoring;
  vpcConstruct: VpcConstruct;
  containerImageConstruct: ContainerImageConstruct;
  prebidCluster: ecs.Cluster;
  glueEtl: GlueEtl;
  cacheConstruct: CacheConstruct;
  datasyncS3Layer: lambda.ILayerVersion;
  operationalMetricsLayer: lambda.ILayerVersion;
  storedRequestsBucket: any;
}

export class ALBEntryDeployment extends Construct {
  public readonly prebidAlb: elbv2.ApplicationLoadBalancer;

  constructor(scope: Construct, id: string, props: ALBEntryDeploymentProps) {
    super(scope, id);

    Aspects.of(this).add(new ConditionAspect(props.deployAlbHttpsCondition));

    const efsConstruct = new EfsConstruct(this, "Efs", props.vpcConstruct.prebidVpc);

    const ecsTaskConstruct = new EcsTaskConstruct(this, "ECSTask", {
      imageEcsObj: props.containerImageConstruct.imageEcsObj,
      prebidFs: efsConstruct.prebidFs,
      prebidFsAccessPoint: efsConstruct.prebidFsAccessPoint,
      dockerConfigsBucket: props.containerImageConstruct.dockerConfigsBucket,
      storedRequestsBucket: props.storedRequestsBucket,
      stackParams: props.stackParams,
    });

    // ALB with open ingress for HTTPS
    const albSg = new ec2.SecurityGroup(this, "Prebid-ALB-security-group", { vpc: props.vpcConstruct.prebidVpc });
    albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), "Allow ingress from any IPv4 address");
    albSg.addIngressRule(ec2.Peer.anyIpv6(), ec2.Port.tcp(80), "Allow ingress from any IPv6 address");
    (albSg.node.findChild("Resource") as ec2.CfnSecurityGroup).addMetadata("guard", {
      SuppressedRules: ["EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE", "SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE", "EC2_SECURITY_GROUP_INGRESS_OPEN_TO_WORLD_RULE", "SECURITY_GROUP_INGRESS_CIDR_NON_32_RULE"],
    });

    this.prebidAlb = new elbv2.ApplicationLoadBalancer(this, "Prebid-ALB", {
      vpc: props.vpcConstruct.prebidVpc,
      internetFacing: true,
      securityGroup: albSg,
    });
    (this.prebidAlb.node.findChild("Resource") as elbv2.CfnLoadBalancer).addMetadata("guard", { SuppressedRules: ["ELBV2_ACCESS_LOGGING_RULE"] });

    // Mainline pins CfnOutput(self, "Prebid-ALBDNSName", key="PrebidALBDNSName", ...). Without an
    // override CDK emits ALBEntryDeploymentPrebidALBDNSName<hash>. Pin it flat (mainline key has no
    // hyphen: "PrebidALBDNSName") for output-naming parity.
    const albDnsOutput = new CfnOutput(this, "Prebid-ALBDNSName", { value: this.prebidAlb.loadBalancerDnsName, description: "Prebid ALB DNS Name" });
    albDnsOutput.overrideLogicalId("PrebidALBDNSName");

    const ecsServiceConstruct = new EcsServiceConstruct(this, "ECSService", {
      stackParams: props.stackParams,
      prebidVpc: props.vpcConstruct.prebidVpc,
      prebidCluster: props.prebidCluster,
      taskDefinition: ecsTaskConstruct.taskDefinition,
      taskSubnets: props.vpcConstruct.prebidTaskSubnets,
      container: ecsTaskConstruct.container,
      prebidFs: efsConstruct.prebidFs,
      albSecGroup: albSg,
    });

    ecsTaskConstruct.container.addEnvironment("CACHE_HOST", ecsServiceConstruct.internalPrebidAlb.loadBalancerDnsName);

    // HTTPS listener with SSL cert
    const httpsListener = this.prebidAlb.addListener("HTTPSListener", {
      port: 443,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      certificates: [elbv2.ListenerCertificate.fromArn(props.stackParams.sslCertificateParam.valueAsString)],
      defaultAction: elbv2.ListenerAction.forward([ecsServiceConstruct.albTargetGroup]),
    });
    (httpsListener.node.findChild("Resource") as elbv2.CfnListener).addMetadata("guard", {
      SuppressedRules: ["ELBV2_LISTENER_SSL_POLICY_RULE", "ELBV2_LISTENER_PROTOCOL_RULE"],
    });

    // Auto-scaling
    ecsServiceConstruct.addCpuScaling();
    ecsServiceConstruct.addMemoryScaling();
    ecsServiceConstruct.addAlbRequestCountScaling(ecsServiceConstruct.albTargetGroup, props.stackParams.requestCountThreshold.valueAsNumber);

    // Cache listener rules
    new elbv2.ApplicationListenerRule(this, "CacheListenerRuleALBOnly", {
      listener: httpsListener,
      priority: 2,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/cache", "/cache/*"]), elbv2.ListenerCondition.httpRequestMethods(["GET"])],
      action: elbv2.ListenerAction.forward([props.cacheConstruct.lambdaTargetExternalAlb]),
    });

    new elbv2.ApplicationListenerRule(this, "CacheListenerRuleALBOnlyInternal", {
      listener: ecsServiceConstruct.internalHttpListener,
      priority: 1,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/cache", "/cache/*"]), elbv2.ListenerCondition.httpRequestMethods(["GET", "POST"])],
      action: elbv2.ListenerAction.forward([props.cacheConstruct.lambdaTargetInternalAlb]),
    });

    // DataSync
    const datasyncMetrics = new DataSyncTask(this, "DataSyncMetrics", {
      vpc: props.vpcConstruct.prebidVpc,
      efsFilesystem: efsConstruct.prebidFs,
      efsAp: efsConstruct.prebidFsAccessPoint,
      efsPath: constants.EFS_METRICS,
      filterPattern: "*/prebid-metrics.log",
      taskSchedule: constants.DATASYNC_METRICS_SCHEDULE,
      reportBucket: props.artifactsConstruct.artifactsBucket,
      logGroup: props.datasyncMonitor.logGroup,
      glueEtlJobTrigger: props.glueEtl.lambdaFunction,
      glueEtlS3Location: props.glueEtl.metricsS3Location,
      transferMode: "CHANGED",
    });
    // Mainline wires these construct-scope deps (alb_entry_deployment.py):
    // datasync_metrics.node.add_dependency(artifacts_bucket / datasync_monitor.log_group).
    // CDK propagates the dependency to every resource in the DataSyncTask subtree
    // (both roles + the task), matching Mainline's synthesized DependsOn.
    datasyncMetrics.node.addDependency(props.artifactsConstruct.artifactsBucket);
    datasyncMetrics.node.addDependency(props.datasyncMonitor.logGroup);

    const datasyncAnalytics = new DataSyncTask(this, "DataSyncAnalytics", {
      vpc: props.vpcConstruct.prebidVpc,
      efsFilesystem: efsConstruct.prebidFs,
      efsAp: efsConstruct.prebidFsAccessPoint,
      efsPath: constants.EFS_ANALYTICS,
      filterPattern: "*/prebid-analytics.log",
      taskSchedule: constants.DATASYNC_ANALYTICS_SCHEDULE,
      reportBucket: props.artifactsConstruct.artifactsBucket,
      logGroup: props.datasyncMonitor.logGroup,
      glueEtlS3Location: props.glueEtl.analyticsS3Location,
      transferMode: "ALL",
    });
    datasyncAnalytics.node.addDependency(props.artifactsConstruct.artifactsBucket);
    datasyncAnalytics.node.addDependency(props.datasyncMonitor.logGroup);

    const efsCleanup = new EfsCleanup(this, "EfsCleanup", {
      vpc: props.vpcConstruct.prebidVpc,
      efsAp: efsConstruct.prebidFsAccessPoint,
      efsFilesystem: efsConstruct.prebidFs,
      reportBucket: props.artifactsConstruct.artifactsBucket,
      datasyncTasks: { metrics: datasyncMetrics.task, analytics: datasyncAnalytics.task },
      fargateClusterArn: props.prebidCluster.clusterArn,
    });
    efsCleanup.efsFileDelLambdaFunction.addLayers(props.datasyncS3Layer);
    efsCleanup.efsFileDelLambdaFunction.addLayers(props.operationalMetricsLayer);
    efsCleanup.containerStopLambdaFunction.addLayers(props.operationalMetricsLayer);

    // Ported from alb_entry_deployment.py: CfnOutput(self, "Prebid-EFSId", ...).
    // Construct-scoped id "Prebid-EFSId" yields the synthesized key
    // ALBEntryDeploymentPrebidEFSId<hash>. The ConditionAspect on this construct
    // applies DeployALBHttpsCondition. NOTE: Mainline's description contains the
    // literal typo "systemd" — reproduced verbatim for byte parity.
    new CfnOutput(this, "Prebid-EFSId", {
      value: efsConstruct.prebidFs.fileSystemId,
      description: "EFS file systemd id",
    });

    // CloudWatch
    new CloudwatchAlarms(this, "CloudwatchAlarms", {
      applicationLoadBalancer: this.prebidAlb,
      efsFileSystem: efsConstruct.prebidFs,
      vpc: props.vpcConstruct.prebidVpc,
      glueJobName: props.glueEtl.GLUE_JOB_NAME,
    });

    new CloudwatchMetricsConstruct(this, "cloudwatch-metrics", {
      publicSubnets: props.vpcConstruct.prebidVpc.publicSubnets.map((s) => s.subnetId),
      loadBalancerFullName: this.prebidAlb.loadBalancerFullName,
      elasticacheClusterId: props.cacheConstruct.serverlessCache.serverlessCacheName,
    });

    new BaseCloudwatchDashboard(this, "PrebidDashboard", {
      applicationLoadBalancer: this.prebidAlb,
      efsFileSystem: efsConstruct.prebidFs,
      vpc: props.vpcConstruct.prebidVpc,
      glueJobName: props.glueEtl.GLUE_JOB_NAME,
      ecsClusterName: props.prebidCluster.clusterName,
      ecsServiceName: ecsServiceConstruct.serviceName,
      albTargetGroup: ecsServiceConstruct.albTargetGroup,
      cacheTargetGroup: props.cacheConstruct.lambdaTargetInternalAlb,
      cacheAlb: ecsServiceConstruct.internalPrebidAlb,
      dataSyncMetricsBucketName: props.glueEtl.metricsSourceBucket.bucketName,
      metricsEtlBucketName: props.glueEtl.outputBucket.bucketName,
      cacheLambdaName: props.cacheConstruct.cacheLambdaFunction.functionName,
      efsCleanupLambdaName: efsCleanup.efsFileDelLambdaFunction.functionName,
      containerStopLambdaName: efsCleanup.containerStopLambdaFunction.functionName,
      glueTriggerLambdaName: props.glueEtl.lambdaFunction.functionName,
      elasticacheClusterId: props.cacheConstruct.serverlessCache.serverlessCacheName,
    });

    new AlbAccessLogsConstruct(this, "ALBAccessLogsConstruct", this.prebidAlb.loadBalancerArn);
  }
}
