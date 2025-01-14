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

import pandas as pd
import joblib
from io import StringIO
import os
import numpy as np
import logging

from sagemaker_containers.beta.framework import (
    encoders, worker)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

feature_columns_names = [
    'Date',
    'location_id',
    'location_parking_type_id'
    'count_of_trx'
]

label_column = ['count_of_trx_1_day_ahead', 'count_of_trx_2_day_ahead', 'count_of_trx_3_day_ahead',
                'count_of_trx_4_day_ahead', 'count_of_trx_5_day_ahead', 'count_of_trx_6_day_ahead',
                'count_of_trx_7_day_ahead', 'count_of_trx_8_day_ahead', 'count_of_trx_9_day_ahead',
                'count_of_trx_10_day_ahead', 'count_of_trx_11_day_ahead', 'count_of_trx_12_day_ahead',
                'count_of_trx_13_day_ahead', 'count_of_trx_14_day_ahead']


def input_fn(input_data, content_type):
    """Parse input data payload

    We currently only take csv input. Since we need to process both labelled
    and unlabelled data we first determine whether the label column is present
    by looking at how many columns were provided.
    """
    logger.info(f"input data {input_data} with format {content_type}")

    if content_type == 'text/csv':
        # Read the raw input data as CSV.
        df = pd.read_csv(StringIO(input_data),
                         header=None)

        if len(df.columns) == len(feature_columns_names) + 14:
            # This is a labelled example, includes the ring label
            df.columns = feature_columns_names + label_column
        elif len(df.columns) == len(feature_columns_names):
            # This is an unlabelled example.
            df.columns = feature_columns_names

        return df
    else:
        raise ValueError("{} not supported by script!".format(content_type))


def output_fn(prediction, accept):
    """Format prediction output.
       XGBoost only support text/csv and text/libsvm. Use text/csv here.
    """
    logger.info(f"output data {prediction}")

    if accept == 'text/csv':
        return worker.Response(encoders.encode(prediction, accept), accept, mimetype=accept)
    else:
        raise ValueError("{} accept type is not supported by this script.".format(accept))


def predict_fn(input_data, model):
    """Preprocess input data

    We implement this because the default predict_fn uses .predict(), but our model is a preprocessor
    so we want to use .transform().

    The output is returned in the following order:

        rest of features either one hot encoded or standardized
    """
    features = model.transform(input_data)

    if label_column in input_data:
        # Return the label (as the first column) and the set of features.
        return np.insert(features, 0, input_data[label_column], axis=1)
    else:
        # Return only the set of features
        return features


def model_fn(model_dir):
    """Deserialize fitted model
    """
    preprocessor = joblib.load(os.path.join(model_dir, "model.joblib"))
    return preprocessor
