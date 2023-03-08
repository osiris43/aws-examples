import aws_cdk as core
import aws_cdk.assertions as assertions

from nginx_otel_ecs_cdk.nginx_otel_ecs_cdk_stack import NginxOtelEcsCdkStack

# example tests. To run these tests, uncomment this file along with the example
# resource in nginx_otel_ecs_cdk/nginx_otel_ecs_cdk_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = NginxOtelEcsCdkStack(app, "nginx-otel-ecs-cdk")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
