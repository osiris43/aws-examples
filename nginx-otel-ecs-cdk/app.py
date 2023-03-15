#!/usr/bin/env python3
import os

import aws_cdk as cdk

from nginx_otel_ecs_cdk.nginx_otel_ecs_cdk_stack import NginxOtelEcsCdkStack


app = cdk.App()
NginxOtelEcsCdkStack(app, "NginxOtelEcsCdkStack",
    env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),
    )

app.synth()
