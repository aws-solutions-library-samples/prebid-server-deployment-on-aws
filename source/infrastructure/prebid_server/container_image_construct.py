# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from aws_cdk import Aws, CfnParameter, CfnOutput
from aws_cdk import aws_ecs as ecs
from constructs import Construct
from aws_cdk.aws_ecr_assets import DockerImageAsset, Platform
from .prebid_configs_construct import PrebidConfigsManager

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ECR_REPO_NAME = os.getenv("ECR_REPO_NAME") or "prebid-server"
PUBLIC_ECR_REGISTRY = os.getenv("PUBLIC_ECR_REGISTRY")
ECR_REPO_TAG = os.getenv("PUBLIC_ECR_TAG") or "latest"
ECR_REGISTRY = os.getenv("OVERRIDE_ECR_REGISTRY")
if not ECR_REGISTRY and (PUBLIC_ECR_REGISTRY and ECR_REPO_TAG):
    ECR_REGISTRY = f"{PUBLIC_ECR_REGISTRY}/{ECR_REPO_NAME}:{ECR_REPO_TAG}"
    logger.debug(f"ECR_REGISTRY: {ECR_REGISTRY}")


class ContainerImageConstruct(Construct):

    def __init__(
            self,
            scope,
            id,
            solutions_template_options,
            stored_requests_bucket
    ) -> None:
        """
        This construct creates Docker image.
        """
        super().__init__(scope, id)

        docker_build_location = self.get_docker_build_location()

        # Deploy Prebid configuration files to S3 bucket
        prebid_configs_manager = PrebidConfigsManager(self, "ConfigFiles", docker_build_location, stored_requests_bucket)
        self.docker_configs_manager_bucket = prebid_configs_manager.docker_config_bucket

        if ECR_REGISTRY is None:
            # When running cdk-deploy, unless ECR_REGISTRY is set we will build the image locally
            logger.info("Prepare ECS container image from image asset.")

            asset = DockerImageAsset(
                self,
                ECR_REPO_NAME,
                directory=docker_build_location,
                platform=Platform.LINUX_AMD64,
            )

            self.image_ecs_obj = ecs.ContainerImage.from_docker_image_asset(asset)
            self.image_ecs_str = asset.image_uri
        else:
            # When our pipeline builds the template, ECR_REGISTRY is set and we use a hosted image
            logger.info("Prepare ECS container image from registry.")
            image_cfn_param = CfnParameter(
                self,
                id="ContainerImage",
                type="String",
                description="The fully qualified name of the Prebid Server container image to deploy.",
                default=ECR_REGISTRY
            )
            solutions_template_options.add_parameter(image_cfn_param, label="PrebidServerContainerImage", group="Container Image Settings")

            self.image_ecs_obj = ecs.ContainerImage.from_registry(image_cfn_param.value_as_string)
            self.image_ecs_str = image_cfn_param.value_as_string

        CfnOutput(self, "PrebidECSImage", value=self.image_ecs_str, description="Prebid Server ECR Image")
        CfnOutput(self, "PrebidSolutionConfigBucket",
                  value=f"https://{Aws.REGION}.console.aws.amazon.com/s3/home?region={Aws.REGION}&bucket={self.docker_configs_manager_bucket.bucket_name}",
                  description="Prebid Solution Configuration Bucket"
                )

    @staticmethod
    def get_docker_build_location():
        docker_build_location = "../../deployment/ecr/prebid-server"
        if os.getcwd().split("/")[-1] == "source":
            docker_build_location = "../deployment/ecr/prebid-server"
        elif os.getcwd().split("/")[-1] == "deployment":
            docker_build_location = "ecr/prebid-server"

        return docker_build_location
