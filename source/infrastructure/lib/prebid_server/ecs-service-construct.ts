// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Duration } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import { Construct } from "constructs";
import { StackParams } from "./stack-cfn-parameters";
import * as constants from "../shared/stack-constants";

export interface EcsServiceConstructProps {
  stackParams: StackParams;
  prebidVpc: ec2.IVpc;
  prebidCluster: ecs.ICluster;
  taskDefinition: ecs.FargateTaskDefinition;
  taskSubnets: ec2.ISubnet[];
  container: ecs.ContainerDefinition;
  prebidFs: efs.FileSystem;
  albSecGroup?: ec2.ISecurityGroup;
}

export class EcsServiceConstruct extends Construct {
  public readonly albTargetGroup: elbv2.ApplicationTargetGroup;
  public readonly scalableTarget: ecs.ScalableTaskCount;
  public readonly internalPrebidAlb: elbv2.ApplicationLoadBalancer;
  public readonly internalHttpListener: elbv2.ApplicationListener;
  public readonly serviceName: string;

  private readonly scaleCooldown: { scaleInCooldown: Duration; scaleOutCooldown: Duration };

  constructor(scope: Construct, id: string, props: EcsServiceConstructProps) {
    super(scope, id);

    const fargateService = new ecs.FargateService(this, "PrebidFargateService", {
      cluster: props.prebidCluster,
      taskDefinition: props.taskDefinition,
      vpcSubnets: { subnets: props.taskSubnets },
      enableECSManagedTags: true,
      propagateTags: ecs.PropagatedTagSource.TASK_DEFINITION,
      circuitBreaker: { enable: true, rollback: true },
      capacityProviderStrategies: [
        { capacityProvider: "FARGATE", weight: constants.FARGATE_RESERVED_WEIGHT },
        {
          capacityProvider: "FARGATE_SPOT",
          weight: props.stackParams.spotInstanceWeight.valueAsNumber,
        },
      ],
    });

    this.serviceName = fargateService.serviceName;

    this.albTargetGroup = new elbv2.ApplicationTargetGroup(this, "ALBTargetGroup", {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      targets: [
        fargateService.loadBalancerTarget({
          containerName: props.container.containerName,
          containerPort: props.container.containerPort,
        }),
      ],
      vpc: props.prebidVpc,
    });

    // Suppress egress rules on Fargate SG
    const fgSg = fargateService.connections.securityGroups[0];
    (fgSg.node.findChild("Resource") as ec2.CfnSecurityGroup).addMetadata("guard", {
      SuppressedRules: [
        "EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE",
        "SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE",
      ],
    });

    // EFS connectivity
    fargateService.connections.allowFrom(props.prebidFs, ec2.Port.tcp(constants.EFS_PORT));
    fargateService.connections.allowTo(props.prebidFs, ec2.Port.tcp(constants.EFS_PORT));

    // Allow ALB to reach ECS tasks on the actual HTTPS container port
    if (props.albSecGroup) {
      fargateService.connections.allowFrom(
        props.albSecGroup,
        ec2.Port.tcp(constants.CONTAINER_PORT),
        "Allow ALB to reach containers on HTTPS port"
      );
    }

    // Health check
    this.albTargetGroup.configureHealthCheck({
      path: constants.HEALTH_PATH,
      interval: Duration.seconds(constants.HEALTH_CHECK_INTERVAL_SECS),
      timeout: Duration.seconds(constants.HEALTH_CHECK_TIMEOUT_SECS),
    });

    // Auto-scaling
    this.scalableTarget = fargateService.autoScaleTaskCount({
      minCapacity: props.stackParams.ecsTaskMinCapacity.valueAsNumber,
      maxCapacity: props.stackParams.ecsTaskMaxCapacity.valueAsNumber,
    });

    this.scaleCooldown = {
      scaleInCooldown: Duration.seconds(constants.SCALE_IN_COOLDOWN_SECS),
      scaleOutCooldown: Duration.seconds(constants.SCALE_OUT_COOLDOWN_SECS),
    };

    // Internal ALB
    const internalAlbSg = new ec2.SecurityGroup(this, "InternalPrebidALBSecurityGroup", {
      vpc: props.prebidVpc,
      description: "Security group for internal Prebid ALB",
      allowAllOutbound: true,
    });
    internalAlbSg.addIngressRule(
      ec2.Peer.securityGroupId(fgSg.securityGroupId),
      ec2.Port.tcp(80),
      "Allow HTTP traffic only from Prebid Fargate service"
    );
    (internalAlbSg.node.defaultChild as ec2.CfnSecurityGroup).addMetadata("guard", {
      SuppressedRules: ["EC2_SECURITY_GROUP_INGRESS_OPEN_TO_WORLD_RULE"],
    });

    this.internalPrebidAlb = new elbv2.ApplicationLoadBalancer(this, "InternalPrebidALB", {
      vpc: props.prebidVpc,
      internetFacing: false,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroup: internalAlbSg,
    });
    (this.internalPrebidAlb.node.findChild("Resource") as elbv2.CfnLoadBalancer).addMetadata("guard", {
      SuppressedRules: ["ELBV2_ACCESS_LOGGING_RULE"],
    });

    this.internalHttpListener = this.internalPrebidAlb.addListener("InternalHTTPListener", {
      port: 80,
      open: false,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.fixedResponse(401, {
        contentType: "text/plain",
        messageBody: "Unauthorized",
      }),
    });
    (this.internalHttpListener.node.findChild("Resource") as elbv2.CfnListener).addMetadata("guard", {
      SuppressedRules: ["ELBV2_LISTENER_PROTOCOL_RULE", "ELBV2_LISTENER_SSL_POLICY_RULE"],
    });

    // Allow ECS tasks to reach internal ALB
    fgSg.addEgressRule(internalAlbSg, ec2.Port.tcp(80), "Allow ECS tasks to access internal ALB");
  }

  public addCpuScaling(): void {
    this.scalableTarget.scaleOnCpuUtilization("FargateServiceCpuScaling", {
      targetUtilizationPercent: constants.CPU_TARGET_UTILIZATION_PCT,
      ...this.scaleCooldown,
    });
  }

  public addMemoryScaling(): void {
    this.scalableTarget.scaleOnMemoryUtilization("FargateServiceMemoryScaling", {
      targetUtilizationPercent: constants.MEMORY_TARGET_UTILIZATION_PCT,
      ...this.scaleCooldown,
    });
  }

  public addAlbRequestCountScaling(
    targetGroup: elbv2.ApplicationTargetGroup,
    requestsPerTarget: number
  ): void {
    this.scalableTarget.scaleOnRequestCount("FargateServiceRequestCountScaling", {
      requestsPerTarget,
      targetGroup,
      ...this.scaleCooldown,
    });
  }
}
