// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// CloudFront Entry Deployment — creates all resources for CloudFront CDN path
// Ported from cloudfront_entry_deployment.py

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
import { CloudFrontWafConstruct } from "./cloudfront-waf-construct";
import { AlbAccessLogsConstruct } from "./alb-access-logs-construct";
import { DataSyncMonitoring, DataSyncTask, EfsCleanup } from "./datasync-constructs";
import { GlueEtl } from "./glue-constructs";
import { CloudwatchMetricsConstruct, CloudFrontDeploymentDashboard } from "./cloudwatch-constructs";
import { CloudwatchAlarms } from "./cloudwatch-alarms-construct";import { CacheConstruct } from "./cache-construct";
import * as constants from "../shared/stack-constants";

export interface CloudFrontEntryDeploymentProps {
  stackParams: StackParams;
  deployCloudFrontWafCondition: CfnCondition;
  artifactsConstruct: ArtifactsManager;
  datasyncMonitor: DataSyncMonitoring;
  vpcConstruct: VpcConstruct;
  containerImageConstruct: ContainerImageConstruct;
  prebidCluster: ecs.Cluster;
  glueEtl: GlueEtl;
  cacheConstruct: CacheConstruct;
  datasyncS3Layer: lambda.ILayerVersion;
  operationalMetricsLayer: lambda.ILayerVersion;
  xHeaderSecretValue: string;
  storedRequestsBucket: any;
}

export class CloudFrontEntryDeployment extends Construct {
  public readonly prebidAlb: elbv2.ApplicationLoadBalancer;

  constructor(scope: Construct, id: string, props: CloudFrontEntryDeploymentProps) {
    super(scope, id);

    Aspects.of(this).add(new ConditionAspect(props.deployCloudFrontWafCondition));

    const efsConstruct = new EfsConstruct(this, "Efs", props.vpcConstruct.prebidVpc);

    const ecsTaskConstruct = new EcsTaskConstruct(this, "ECSTask", {
      imageEcsObj: props.containerImageConstruct.imageEcsObj,
      prebidFs: efsConstruct.prebidFs,
      prebidFsAccessPoint: efsConstruct.prebidFsAccessPoint,
      dockerConfigsBucket: props.containerImageConstruct.dockerConfigsBucket,
      storedRequestsBucket: props.storedRequestsBucket,
      stackParams: props.stackParams,
    });

    // ALB
    const albSg = new ec2.SecurityGroup(this, "Prebid-ALB-security-group", { vpc: props.vpcConstruct.prebidVpc });
    (albSg.node.findChild("Resource") as ec2.CfnSecurityGroup).addMetadata("guard", {
      SuppressedRules: ["EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE", "SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE", "EC2_SECURITY_GROUP_INGRESS_OPEN_TO_WORLD_RULE", "SECURITY_GROUP_INGRESS_CIDR_NON_32_RULE"],
    });

    this.prebidAlb = new elbv2.ApplicationLoadBalancer(this, "Prebid-ALB", {
      vpc: props.vpcConstruct.prebidVpc,
      internetFacing: true,
      securityGroup: albSg,
    });
    (this.prebidAlb.node.findChild("Resource") as elbv2.CfnLoadBalancer).addMetadata("guard", { SuppressedRules: ["ELBV2_ACCESS_LOGGING_RULE"] });

    const httpListener = this.prebidAlb.addListener("HTTPListener", {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.fixedResponse(401, { contentType: "text/plain", messageBody: "Unauthorized" }),
    });
    (httpListener.node.findChild("Resource") as elbv2.CfnListener).addMetadata("guard", {
      SuppressedRules: ["ELBV2_LISTENER_SSL_POLICY_RULE", "ELBV2_LISTENER_PROTOCOL_RULE"],
    });

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

    const cfWaf = new CloudFrontWafConstruct(this, "CloudFrontWaf", this.prebidAlb, props.xHeaderSecretValue);

    // Set CACHE_HOST to CloudFront domain
    ecsTaskConstruct.container.addEnvironment("CACHE_HOST", cfWaf.prebidCloudFrontDistribution.domainName);

    // Listener rules
    new elbv2.ApplicationListenerRule(this, "PrebidListenerRule1", {
      listener: httpListener,
      priority: 5,
      conditions: [elbv2.ListenerCondition.httpHeader(constants.X_SECRET_HEADER_NAME, [props.xHeaderSecretValue])],
      action: elbv2.ListenerAction.forward([ecsServiceConstruct.albTargetGroup]),
    });

    new elbv2.ApplicationListenerRule(this, "CacheListenerRuleCloudFront", {
      listener: httpListener,
      priority: 2,
      conditions: [
        elbv2.ListenerCondition.pathPatterns(["/cache", "/cache/*"]),
        elbv2.ListenerCondition.httpHeader(constants.X_SECRET_HEADER_NAME, [props.xHeaderSecretValue]),
      ],
      action: elbv2.ListenerAction.forward([props.cacheConstruct.lambdaTargetExternalCf]),
    });

    new elbv2.ApplicationListenerRule(this, "CacheListenerRuleCloudFrontInternal", {
      listener: ecsServiceConstruct.internalHttpListener,
      priority: 1,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/cache", "/cache/*"]), elbv2.ListenerCondition.httpRequestMethods(["GET", "POST"])],
      action: elbv2.ListenerAction.forward([props.cacheConstruct.lambdaTargetInternalCf]),
    });

    // Mainline pins CfnOutput(self, "Prebid-CloudFrontDistributionEndpoint",
    // key="PrebidCloudFrontDistributionEndpoint", ...). Without an override CDK emits the
    // path-prefixed/hash-suffixed key CloudFrontEntryDeploymentPrebidCloudFrontDistributionEndpoint<hash>.
    // Pin it flat for mainline output-naming parity.
    const cfEndpointOutput = new CfnOutput(this, "Prebid-CloudFrontDistributionEndpoint", {
      value: cfWaf.prebidCloudFrontDistribution.domainName,
      description: "Prebid CloudFront Distribution Endpoint",
    });
    cfEndpointOutput.overrideLogicalId("PrebidCloudFrontDistributionEndpoint");

    // Ported from cloudfront_entry_deployment.py:
    // CfnOutput(self, "Prebid-WAF-WebACL", key="PrebidWAFWebACL", ...).
    // Mainline sets an explicit key, so use overrideLogicalId to produce the flat
    // (non-path-prefixed) key "PrebidWAFWebACL". Value is GetAtt <WafWebAclCr>.webacl_name.
    // The ConditionAspect on this construct applies DeployCloudFrontWafCondition.
    const wafWebAclOutput = new CfnOutput(this, "Prebid-WAF-WebACL", {
      value: cfWaf.wafWebaclName,
      description: "Prebid WAF WebACL",
    });
    wafWebAclOutput.overrideLogicalId("PrebidWAFWebACL");

    // ECS Service output (consumed by deployment/simulator_fabric_link.py).
    // Mainline pins CfnOutput(self, "EcsServiceName", key="EcsServiceName", ...). This output is
    // created inside the CloudFrontEntryDeployment construct, so without an override CDK emits a
    // path-prefixed, hash-suffixed key (e.g. CloudFrontEntryDeploymentEcsServiceName1E84C39A).
    // simulator_fabric_link.py reads it by EXACT key (outputs.get("EcsServiceName")), so pin it flat.
    const ecsServiceNameOutput = new CfnOutput(this, "EcsServiceName", {
      value: ecsServiceConstruct.serviceName,
      description: "ECS Service Name",
    });
    ecsServiceNameOutput.overrideLogicalId("EcsServiceName");

    // CloudFront prefix list ingress
    albSg.addIngressRule(ec2.Peer.prefixList(cfWaf.prefixListId), ec2.Port.tcp(80), "Allow ingress only from CloudFront");

    // Auto-scaling
    ecsServiceConstruct.addCpuScaling();
    ecsServiceConstruct.addMemoryScaling();
    ecsServiceConstruct.addAlbRequestCountScaling(ecsServiceConstruct.albTargetGroup, props.stackParams.requestCountThreshold.valueAsNumber);

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
    // Mainline wires these construct-scope deps (cloudfront_entry_deployment.py):
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

    // EFS Cleanup
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

    // Ported from cloudfront_entry_deployment.py: CfnOutput(self, "Prebid-EFSId", ...).
    // Construct-scoped id "Prebid-EFSId" yields the synthesized key
    // CloudFrontEntryDeploymentPrebidEFSId<hash>. The ConditionAspect on this
    // construct applies DeployCloudFrontWafCondition.
    new CfnOutput(this, "Prebid-EFSId", {
      value: efsConstruct.prebidFs.fileSystemId,
      description: "Prebid EFS Id",
    });

    // CloudWatch
    new CloudwatchAlarms(this, "CloudwatchAlarms", {
      applicationLoadBalancer: this.prebidAlb,
      efsFileSystem: efsConstruct.prebidFs,
      vpc: props.vpcConstruct.prebidVpc,
      glueJobName: props.glueEtl.GLUE_JOB_NAME,
      cloudfrontDistribution: cfWaf.prebidCloudFrontDistribution,
      wafWebaclName: cfWaf.wafWebaclName,
    });

    new CloudwatchMetricsConstruct(this, "cloudwatch-metrics", {
      cloudFrontId: cfWaf.prebidCloudFrontDistribution.distributionId,
      publicSubnets: props.vpcConstruct.prebidVpc.publicSubnets.map((s) => s.subnetId),
      loadBalancerFullName: this.prebidAlb.loadBalancerFullName,
      elasticacheClusterId: props.cacheConstruct.serverlessCache.serverlessCacheName,
    });

    new CloudFrontDeploymentDashboard(this, "PrebidDashboard", {
      applicationLoadBalancer: this.prebidAlb,
      efsFileSystem: efsConstruct.prebidFs,
      vpc: props.vpcConstruct.prebidVpc,
      glueJobName: props.glueEtl.GLUE_JOB_NAME,
      cloudfrontDistribution: cfWaf.prebidCloudFrontDistribution,
      wafWebaclName: cfWaf.wafWebaclName,
      ecsClusterName: props.prebidCluster.clusterName,
      ecsServiceName: ecsServiceConstruct.serviceName,
      albTargetGroup: ecsServiceConstruct.albTargetGroup,
      cacheTargetGroup: props.cacheConstruct.lambdaTargetInternalCf,
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
