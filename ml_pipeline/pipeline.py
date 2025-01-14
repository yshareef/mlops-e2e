# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.

# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.                                                                              *

"""Example workflow pipeline script for abalone pipeline.

                                               . -RegisterModel
                                              .
    Process-> Train -> Evaluate -> Condition .
                                              .
                                               . -(stop)

Implements a get_pipeline(**kwargs) method.
"""
import os

import boto3
import sagemaker
import sagemaker.session
# from sagemaker.model_metrics import (
#     MetricsSource,
#     ModelMetrics
# )
# from sagemaker.transformer import Transformer
from sagemaker.sklearn.estimator import SKLearn
from sagemaker.inputs import TrainingInput

from sagemaker.processing import (
    ProcessingInput,
    ProcessingOutput
)
# from sagemaker.workflow.pipeline_context import PipelineSession
# from sagemaker.model import Model

from sagemaker.sklearn.processing import SKLearnProcessor
# from sagemaker.sklearn import SKLearnModel
# from sagemaker.workflow.functions import Join
# from sagemaker.workflow.model_step import ModelStep

from sagemaker.workflow.parameters import (
    ParameterInteger,
    ParameterString
)
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.steps import (
    ProcessingStep,
    TrainingStep
    # ,TransformStep

)

# from sagemaker.pipeline import PipelineModel
# from sagemaker.workflow.step_collections import RegisterModel

from sagemaker.workflow.lambda_step import LambdaStep
from sagemaker.lambda_helper import Lambda

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def get_session(region, default_bucket):
    """Gets the sagemaker session based on the region.

    Args:
        region: the aws region to start the session
        default_bucket: the bucket to use for storing the artifacts

    Returns:
        `sagemaker.session.Session instance
    """

    boto_session = boto3.Session(region_name=region)

    sagemaker_client = boto_session.client("sagemaker")
    runtime_client = boto_session.client("sagemaker-runtime")
    return sagemaker.session.Session(
        boto_session=boto_session,
        sagemaker_client=sagemaker_client,
        sagemaker_runtime_client=runtime_client,
        default_bucket=default_bucket,
    )


def get_pipeline(
        region,
        role=None,
        default_bucket=None,
        model_package_group_name="AbaloneModelPackageGroup",
        pipeline_name="AbalonePipeline",
        base_job_prefix="Abalone",
):
    """Gets a SageMaker ML Pipeline instance working with on abalone data.

    Args:
        region: AWS region to create and run the pipeline.
        role: IAM role to create and run steps and pipeline.
        default_bucket: the bucket to use for storing the artifacts

    Returns:
        an instance of a pipeline
    """
    sagemaker_session = get_session(region, default_bucket)
    if role is None:
        role = sagemaker.session.get_execution_role(sagemaker_session)

    # parameters for pipeline execution
    processing_instance_count = ParameterInteger(name="ProcessingInstanceCount", default_value=1)
    processing_instance_type = ParameterString(
        name="ProcessingInstanceType", default_value="ml.m5.large"
    )
    training_instance_type = ParameterString(
        name="TrainingInstanceType", default_value="ml.m5.large"
    )
    model_approval_status = ParameterString(
        name="ModelApprovalStatus", default_value="Approved"
    )

    # batch_data = ParameterString(
    #     name="BatchData",
    #     default_value="s3://rl-batch-transform-dataset/data.csv",
    # )

    # processing step for feature engineering
    sklearn_processor = SKLearnProcessor(
        framework_version="1.2-1",
        instance_type=processing_instance_type,
        instance_count=processing_instance_count,
        base_job_name=f"{base_job_prefix}/sklearn-preprocess",
        sagemaker_session=sagemaker_session,
        role=role,
    )
    print("FINISH - SKPROCESSOR")
    f = open(os.path.join(BASE_DIR, "..", "dataManifest.json"))
    step_process = ProcessingStep(
        name="PreprocessData",
        processor=sklearn_processor,
        outputs=[
            ProcessingOutput(output_name="train", source="/opt/ml/processing/train"),
            ProcessingOutput(output_name="test", source="/opt/ml/processing/test"),
            ProcessingOutput(output_name="data_to_predict", source="/opt/ml/processing/transform"),
            ProcessingOutput(output_name="model", source="/opt/ml/processing/model"),
        ],
        code=os.path.join(BASE_DIR, "..", "src", "preprocess.py"),
        job_arguments=["--data-manifest", f.read()],
    )

    f.close()
    print("FINISH - PROCESSING STEP")

    # training step for generating model artifacts
    script_path = os.path.join(BASE_DIR, "..", "src", "train.py")
    model_path = f"s3://{sagemaker_session.default_bucket()}/{base_job_prefix}/Train"
    FRAMEWORK_VERSION = "1.2-1"
    ridge_train = SKLearn(
        entry_point=script_path,
        framework_version=FRAMEWORK_VERSION,
        instance_type=training_instance_type,
        output_path=model_path,
        sagemaker_session=sagemaker_session,
        role=role,
        hyperparameters={"alpha": 10}
    )
    print("FINISH - SKLEARN")

    step_train = TrainingStep(
        name="TrainModel",
        estimator=ridge_train,
        inputs={
            "train": TrainingInput(
                s3_data=step_process.properties.ProcessingOutputConfig.Outputs[
                    "train"
                ].S3Output.S3Uri,
                content_type="text/csv",
            )
        }
    )

    print("FINISH - TRAINING")

    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json",
    )

    print("FINISH - EV-REPORT")

    step_eval = ProcessingStep(
        name="EvaluateModel",
        processor=sklearn_processor,
        inputs=[
            ProcessingInput(
                source=step_train.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=step_process.properties.ProcessingOutputConfig.Outputs[
                    "test"
                ].S3Output.S3Uri,
                destination="/opt/ml/processing/test",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="evaluation", source="/opt/ml/processing/evaluation"),
        ],
        code=os.path.join(BASE_DIR, "..", "src", "evaluate.py"),
        property_files=[evaluation_report],
    )
    print("FINISH - EV step")

    step_predict = ProcessingStep(
        name="Predictions",
        processor=sklearn_processor,
        inputs=[
            ProcessingInput(
                source=step_train.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=step_process.properties.ProcessingOutputConfig.Outputs[
                    "data_to_predict"
                ].S3Output.S3Uri,
                destination="/opt/ml/processing/transform",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="predictions", source="/opt/ml/processing/predictions"),
        ],
        code=os.path.join(BASE_DIR, "..", "src", "inference.py")
    )
    print("FINISH - Predictions step")

    # Define the Lambda function
    lambda_function = Lambda(
        function_arn="arn:aws:lambda:us-east-2:471112887763:function:rl-mlops-e2e-prediction-data-postprocessing-lambda")

    # Create the Lambda step
    lambda_step = LambdaStep(
        name="LambdaStepWriteToRDS",
        lambda_func=lambda_function,
        inputs={
            "LocationDataS3Uri": step_process.properties.ProcessingOutputConfig.Outputs[
                "data_to_predict"].S3Output.S3Uri,
            "PredictionsDataS3Uri": step_predict.properties.ProcessingOutputConfig.Outputs[
                "predictions"].S3Output.S3Uri}
    )

    # # register model step that will be conditionally executed
    # model_metrics = ModelMetrics(
    #     model_statistics=MetricsSource(
    #         s3_uri="{}/evaluation.json".format(
    #             step_eval.arguments["ProcessingOutputConfig"]["Outputs"][0]["S3Output"]["S3Uri"]
    #         ),
    #         content_type="application/json",
    #     )
    # )
    # print("FINISH - METRICS")

    # sklearn_model = SKLearnModel(
    #     name='SKLearnTransform',
    #     entry_point=os.path.join(BASE_DIR, "..", "src", "transform.py"),
    #     role=role,
    #     framework_version="1.2-1",
    #     py_version="py3",
    #     sagemaker_session=sagemaker_session,
    #     model_data=Join(on='/', values=[step_process.properties.ProcessingOutputConfig.Outputs[
    #                                         "model"].S3Output.S3Uri, "model.tar.gz"]), )
    # print("FINISH - SK MODEL")

    # Define the batch transform step

    # Define the model
    # image_uri = sagemaker.image_uris.retrieve(
    #     framework="xgboost",
    #     region=region,
    #     version="1.0-1",
    #     py_version="py3",
    #     instance_type="ml.m5.large",
    # )

    # # # Retrieve the Scikit-learn image URI
    # model_inference_path = f"s3://{sagemaker_session.default_bucket()}/{base_job_prefix}/Inference"
    # inference_path = os.path.join(BASE_DIR, "..", "src", "inference.py")
    # # sklearn_image_uri = sagemaker.image_uris.retrieve(
    # #     framework='sklearn',
    # #     region=region,
    # #     version='1.2-1',  # specify your desired version
    # #     py_version='py3',
    # #     instance_type='ml.m5.large',  # specify the instance type for inference,
    # #     entry_point=inference_path,
    # #     output_path=model_inference_path
    # # )
    #
    # ridge_inference = SKLearn(
    #     entry_point=inference_path,
    #     framework_version=FRAMEWORK_VERSION,
    #     instance_type=training_instance_type,
    #     output_path=model_inference_path,
    #     sagemaker_session=sagemaker_session,
    #     role=role
    # )
    #
    # model = Model(
    #     image_uri=ridge_inference.training_image_uri(),
    #     model_data=step_train.properties.ModelArtifacts.S3ModelArtifacts,
    #     sagemaker_session=PipelineSession(),
    #     role=role,
    #     env={"SAGEMAKER_DEFAULT_INVOCATIONS_ACCEPT": "text/csv",
    #          "SAGEMAKER_USE_NGINX": "True",
    #          "SAGEMAKER_WORKER_CLASS_TYPE": "gevent",
    #          "SAGEMAKER_KEEP_ALIVE_SEC": "60",
    #          "SAGEMAKER_CONTAINER_LOG_LEVEL": "20",
    #          "SAGEMAKER_PROGRAM": "my-script.py",
    #          "SAGEMAKER_REGION": "us-east-2",
    #          "SAGEMAKER_SUBMIT_DIRECTORY": "s3://my-bucket/my-key/source/sourcedir.tar.gz"
    #          }
    # )
    # print("Define the model-Done")
    #
    # # Model Step
    # step_create_model = ModelStep(
    #     name="ModelCreationStep",
    #     step_args=model.create()
    # )
    # print("step_create_model-Done")
    #
    # transformer = Transformer(
    #     model_name=step_create_model.properties.ModelName,
    #     instance_type="ml.m5.large",
    #     instance_count=1,
    #     output_path=f"s3://{default_bucket}/Transform",
    #     sagemaker_session=PipelineSession()
    # )
    # print("Define the transformer-Done")
    #
    # # Define the batch transform step
    # step_transform = TransformStep(
    #     name="BatchTransform",
    #     step_args=transformer.transform(data="s3://rl-batch-transform-dataset/data.csv")
    # )
    # print("Define the step_transform-Done")

    # step_create_model = ModelStep(
    #     name="AbaloneCreateModel",
    #     step_args=sklearn_model.create(instance_type="ml.m5.large"),
    # )
    #
    # # Create a Transformer object
    # transformer = Transformer(
    #     model_name=step_create_model.properties.ModelName,
    #     instance_count=1,
    #     instance_type='ml.m5.large',
    #     output_path=f"s3://{sagemaker_session.default_bucket()}/{base_job_prefix}/Transform",
    #     sagemaker_session=sagemaker_session
    # )
    #
    # # Define the TransformStep
    # step_transform = TransformStep(
    #     name="BatchTransform",
    #     transformer=transformer,
    #     inputs=sagemaker.inputs.TransformInput(data="s3://rl-batch-transform-dataset/data.csv")
    # )
    #

    # model = PipelineModel(
    #     name='PipelineModel',
    #     role=role,
    #     models=[
    #         sklearn_model
    #     ]
    # )
    # print("FINISH - MODEL")

    # step_register_inference_model = RegisterModel(
    #     name="RegisterModel",
    #     estimator=ridge_train,
    #     content_types=["text/csv"],
    #     response_types=["text/csv"],
    #     transform_instances=["ml.m5.large"],
    #     model_package_group_name=model_package_group_name,
    #     approval_status=model_approval_status,
    #     model_metrics=model_metrics,
    #     model=model
    # )
    # print("FINISH - REGISTER")

    # condition step for evaluating model quality and branching execution
    # cond_lte = ConditionLessThanOrEqualTo(
    #     left=JsonGet(
    #         step=step_eval,
    #         property_file=evaluation_report,
    #         json_path="regression_metrics.mse.value",
    #     ),
    #     right=70,
    # )
    #
    # print("FINISH - COND1")
    #
    # step_cond = ConditionStep(
    #     name="CheckMSEEvaluation",
    #     conditions=[cond_lte],
    #     if_steps=[step_register_inference_model],
    #     else_steps=[],
    # )
    # print("FINISH - COND STEP")

    # pipeline instance
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            processing_instance_type,
            processing_instance_count,
            training_instance_type,
            model_approval_status
        ],
        steps=[step_process, step_train, step_eval, step_predict, lambda_step],
        sagemaker_session=sagemaker_session,
    )

    print("FINISH - PIPELINE")

    return pipeline
