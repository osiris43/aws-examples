from aws_cdk import (
    Stack,
    aws_ecr as ecr,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_route53 as route53,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_s3 as s3,
)
from constructs import Construct


class NginxOtelEcsCdkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env_ctx = dict(self.node.try_get_context("cluster-data"))

        subnets = []
        azs = []
        for region, subnet_id in env_ctx["subnets"].items():
            subnets.append(subnet_id)
            azs.append(region)

        vpc = ec2.Vpc.from_vpc_attributes(
            self,
            "VPC",
            vpc_id=env_ctx["vpc_id"],
            public_subnet_ids=subnets,
            availability_zones=azs,
        )
        cluster = ecs.Cluster(
            self,
            f"otel-gateway-cluster",
            cluster_name=f"otel-gateway",
            vpc=vpc,
        )

        execution_role = iam.Role(
            self,
            f"otelgateway-execution-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name=f"otelgateway-execution-role",
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=["*"],
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
            )
        )

        # Uncomment and add your customer zone here.
        # zone = route53.HostedZone.from_hosted_zone_attributes(
        #     self,
        #     "hosted-zone",
        #     hosted_zone_id="Z1LM4JT47QQL17",
        #     zone_name="your-hosted-zone-name",
        # )

        load_balanced_fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "otel-gateway-service",
            service_name="otel-gateway-service",
            cluster=cluster,
            memory_limit_mib=512,
            redirect_http=True,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            # Uncomment these for a public domain, set up by the zone above.
            # domain_name=env_ctx["domain-name"],
            # domain_zone=zone,
            cpu=256,
            assign_public_ip=True,
            task_definition=self.build_task_definition(execution_role),
        )

        load_balanced_fargate_service.target_group.configure_health_check(
            port="80",
            healthy_http_codes="200-299",
            unhealthy_threshold_count=10,
            path="/health",
        )

        scalable_target = load_balanced_fargate_service.service.auto_scale_task_count(
            min_capacity=1, max_capacity=2
        )

        scalable_target.scale_on_cpu_utilization(
            "CpuScaling", target_utilization_percent=60
        )

        scalable_target.scale_on_memory_utilization(
            "MemoryScaling", target_utilization_percent=60
        )

        # turn on access logs to ship to honeycomb for monitoring
        bucket = s3.Bucket.from_bucket_arn(
            self,
            "ALBLogsBucket",
            bucket_arn="arn:aws:s3:::beacon-otel-gateway-alb-logs",
        )
        load_balanced_fargate_service.load_balancer.log_access_logs(bucket=bucket)

    def build_task_definition(self, execution_role):
        # Where your collector images live
        ecr_repository = ecr.Repository.from_repository_name(
            self,
            "otel-image-repository",
            repository_name="your-repository-name-with-collector-images",
        )

        # where the nginx image with appropriate configuration lives.
        nginx_repository = ecr.Repository.from_repository_name(
            self,
            "otel-gateway-nginx",
            repository_name="your-repository-name-with-nginx-images",
        )
        fargate_task_definition = ecs.FargateTaskDefinition(
            self,
            "otel-task-definition",
            memory_limit_mib=512,
            cpu=256,
            execution_role=execution_role,
        )

        # Reverse proxy infra
        nginx_container = fargate_task_definition.add_container(
            "NginxContainer",
            image=ecs.ContainerImage.from_ecr_repository(nginx_repository),
            essential=True,
            logging=ecs.LogDrivers.aws_logs(
                log_group=logs.LogGroup(
                    self,
                    "otel-nginx-lg",
                    log_group_name="/aws/fargate/nginx-otel-gateway",
                    retention=logs.RetentionDays.ONE_WEEK,
                ),
                stream_prefix=f"nginx-otel-gateway",
            ),
        )
        nginx_container.add_port_mappings(ecs.PortMapping(container_port=80))

        # OTEL Collector infra
        otel_mappings = []
        otel_mappings.append(ecs.PortMapping(container_port=4318))
        otel_mappings.append(ecs.PortMapping(container_port=4317))
        otel_mappings.append(ecs.PortMapping(container_port=13133))

        otel_container = fargate_task_definition.add_container(
            f"otel-container",
            container_name="app",
            #
            image=ecs.ContainerImage.from_ecr_repository(ecr_repository),
            essential=False,
            logging=ecs.LogDrivers.aws_logs(
                log_group=logs.LogGroup(
                    self,
                    "otel-gateway-lg",
                    log_group_name="/aws/fargate/otel-gateway",
                    retention=logs.RetentionDays.ONE_WEEK,
                ),
                stream_prefix=f"otel-gateway",
            ),
            port_mappings=otel_mappings,
            # You can add environment variables here if necessary
            # environment={
            #     "BEACON_ENVIRONMENT": "your environment"
            # },
        )

        # Set up a dependency so that the nginx container doesn't start
        # and die before the otel collector is running.
        nginx_container.add_container_dependencies(
            ecs.ContainerDependency(
                container=otel_container,
                condition=ecs.ContainerDependencyCondition.START,
            )
        )
        return fargate_task_definition
