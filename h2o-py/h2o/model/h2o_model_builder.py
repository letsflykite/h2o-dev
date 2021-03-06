"""
An abstract model builder.
"""

import abc

from ..h2o import H2OFrame
from ..frame import H2OVec
from ..h2o import H2OConnection
from . import ModelBase
from ..h2o import H2OJob
from binomial import H2OBinomialModel
from multinomial import H2OMultinomialModel
from clustering import H2OClusteringModel
from regression import H2ORegressionModel
import h2o

from math import isinf  # needed because st00pid backend doesn't read inf
import sys


class H2OMissingFrameError(Exception):
    pass


class H2OUnknownModelError(Exception):
    pass


class H2OModelBuilder(ModelBase):
    """Abstract base class for H2O Model Builder objects

    Every model depends on a builder.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, parameters=None, algo="", training_frame=None):
        super(H2OModelBuilder, self).__init__()

        # IN
        self._algo = algo
        self._parameters = parameters
        self.training_frame = training_frame

        # OUT
        self._model_type = "H2O{}Model"  # (e.g. "Binomial")
        self._fitted_model = None  # filled after a call to self.fit
        self._model_key = None     # filled after a call to self.fit

    def fit(self, x=None, y=None, validation_frame=None):
        """
        Fit the model to the inputs x, y
        :param x: A list[] of 0-based indices or column names.
        :param y: A 0-based index or a column name
        :return: Returns self (a fitted model).
        """

        # Update self.parameters with any changes to the member vars
        saved_parameters = self._update()

        # check that x and y are not both None and update self._parameters
        x, y = self._set_and_check_x_y(x, y)

        # check that the training_frame is a H2OFrame, and check that the x's are valid
        dataset = self._check_training_frame(x)

        # swap out column indices (0-based) for column names
        x, y = H2OModelBuilder._indexed_columns_to_named_columns(x, y, dataset)

        # set the ignored_columns parameter
        self._set_ignored_columns(x, y, dataset)

        # set the ignored_columns list into self._parameters
        if y:  # y is None for Unsupervised Learner (e.g. CLUSTERING)
            self._set_response_column(y)

        # cbind the H2OVecs and create a tmp key and put this key into self._parameters
        self._set_training_frame(dataset)

        # set the validation frame (similar to _set_training_frame)
        self._set_validation_frame(validation_frame)

        # fold default parameters from H2O and user-specified parameters together
        model_params = self._fold_default_params_with_user_params()

        # launch the job and poll
        url_suffix = "ModelBuilders/" + self._algo
        job_type = self._algo + " Model Build"
        j = H2OJob(H2OConnection.post_json(url_suffix=url_suffix, params=model_params),
                   job_type=job_type).poll()

        # set the fitted_model and model_type fields
        self._set_fitted_model_and_model_type(j.destination_key)

        # do some cleanup
        h2o.remove(self._parameters["training_frame"])
        if "validation_frame" in self._parameters and \
                self._parameters["validation_frame"] is not None:
            h2o.remove(self._parameters["validation_frame"])

        # flowing return
        self._parameters = saved_parameters
        return self

    def model_performance(self, test_data=None):
        if self._fitted_model is None:
            raise ValueError("No model available. Did you call fit()?")
        return self._fitted_model.model_performance(test_data=test_data)

    def predict(self, test_data=None, **kwargs):
        """
        Predict on a data set.
        :param test_data: A set of data that is compatible with the model.
        :return: A new H2OFrame filled with predictions.
        """
        if not test_data:
            raise ValueError("Must specify test data")

        # cbind the test_data vecs together and produce a temp key
        test_data_key = H2OFrame.send_frame(test_data)

        # get the predictions
        url_suffix = "Predictions/models/" + self._model_key + "/frames/" + test_data_key

        # this job call is blocking
        j = H2OConnection.post_json(url_suffix=url_suffix)

        # retrieve the prediction frame
        prediction_frame_key = j["model_metrics"][0]["predictions"]["key"]["name"]

        # get the actual frame meta dta
        pred_frame_meta = h2o.frame(prediction_frame_key)["frames"][0]

        # collect the veckeys
        veckeys = pred_frame_meta["veckeys"]

        # get the number of rows
        rows = pred_frame_meta["rows"]

        # get the column names
        cols = [col["label"] for col in pred_frame_meta["columns"]]

        # create a set of H2OVec objects
        vecs = H2OVec.new_vecs(zip(cols, veckeys), rows)

        # toast the cbound frame
        h2o.remove(self._parameters["training_frame"])

        # return a new H2OFrame object
        return H2OFrame(vecs=vecs)

    def summary(self):
        self._fitted_model.summary()

    # All "private" methods below.

    def _update(self):
        o = self
        a = [n for n in dir(o) if not callable(getattr(o, n)) and not n.startswith("_")]
        self._parameters = dict(zip(a, [getattr(o, i) for i in a]))
        for key in self._parameters:
            if isinstance(self._parameters[key], float):
                if isinf(self._parameters[key]):
                    self._parameters[key] = sys.maxint
        return self._parameters

    def _set_and_check_x_y(self, x, y):
        ret_x = x
        ret_y = y
        if not x or not y:
            if not self._parameters["x"]:  # y is None for Unsupervised, don't check it!
                raise ValueError("No fit can be made, missing feature variables.")
            if x:
                self._parameters["x"] = x
            if y:
                self._parameters["y"] = y

            # return the thing that was changed
            ret_x = self._parameters["x"]

            # if no "y", then we're doing unsupervised learning
            ret_y = None if "y" not in self._parameters.keys() else self._parameters["y"]

        return ret_x, ret_y

    def _check_training_frame(self, x):
        if not self.training_frame:
            raise H2OMissingFrameError("No training frame supplied.")

        dataset = self.training_frame

        if not isinstance(dataset, H2OFrame):
            raise ValueError("`training_frame` must be a H2OFrame. Got: "
                             + str(type(dataset)))

        if not self.training_frame[x]:
            raise ValueError(x + " must be column(s) in " + str(dataset))

        return dataset

    @staticmethod
    def _indexed_columns_to_named_columns(x, y, dataset):
        if isinstance(x[0], int):
            x = [dataset.names()[i] for i in x]
        if y:  # y is None for Unsupervised Learner (e.g. CLUSTERING)
            if isinstance(y, int):
                y = dataset.names()[y]
        return x, y

    def _set_ignored_columns(self, x, y, dataset):
        self._parameters["ignored_columns"] = \
            [i for i in dataset.names() if i not in x and i != y]

    def _set_response_column(self, y):
        self._parameters["response_column"] = y

    def _set_training_frame(self, dataset):
        # Since H2O Frames are a collection of H2OVecs, there is no "frame_key"
        # The method `send_frame` cbinds the frame together and gives it a key.
        dataset_key = H2OFrame.send_frame(dataset)
        self._parameters["training_frame"] = dataset_key

    def _set_validation_frame(self, validation_frame):

        if validation_frame or "validation_frame" in self._parameters.keys():

            if not validation_frame and not self._parameters["validation_frame"]:
                return

            #   Two ways to get the validation set in:
            #       A. It was passed in from the model builder
            #       B. It was passed in to the fit method
            validation_passed_to_fit = False

            if validation_frame:
                # even if self._parameters["validation"] is not None, the one passed to
                # the `fit` call is king.
                self._parameters["validation_frame"] = validation_frame
                validation_passed_to_fit = True

            validation_frame = self._parameters["validation_frame"]

            message = "Validation passed to " + \
                      ("fit" if validation_passed_to_fit else "model builder")
            if not isinstance(validation_frame, H2OFrame):
                raise ValueError(message + " must be of type H2OFrame. "
                                           "Got: " + str(type(validation_frame)))

            # see the comment in _set_training_frame for more on send_frame
            validation_key = H2OFrame.send_frame(validation_frame)
            self._parameters["validation_frame"] = validation_key

    def _fold_default_params_with_user_params(self):
        """
        Fold together the user parameters with the default parameters
        :return: A single dictionary of parameters
        """
        url_suffix = "ModelBuilders/" + self._algo

        # ask h2o what the default parameters are
        builders_response = H2OConnection.get_json(url_suffix=url_suffix)

        # fish out the parameters from the builders_response json object
        model_params_raw = builders_response["model_builders"][self._algo]["parameters"]

        # build a dictionary of the default parameters that self._algo expects
        model_params_default = {n["name"]: n["default_value"] for n in model_params_raw}

        # take values from self.params if they map to model_params
        params_to_fill = [k for k in self._parameters.keys() if k in model_params_default]

        # fill in the default parameters with the user-specified values
        for k in params_to_fill:
            model_params_default[k] = self._parameters[k]

        keys_to_pop = []
        for k in model_params_default:
            if model_params_default[k] is None:
                keys_to_pop += [k]

        if len(keys_to_pop) > 0:
            for k in keys_to_pop:
                model_params_default.pop(k, None)

        # return the default parameters folded together with the user-specified params
        return model_params_default

    def _set_fitted_model_and_model_type(self, destination_key):

        # first set the model key
        self._model_key = destination_key

        # GET the model result
        url_suffix = "Models/" + destination_key
        model = H2OConnection.get_json(url_suffix=url_suffix)["models"][0]

        # get the model type
        self._model_type = self._model_type.format(model["output"]["model_category"])
        
        # Create the type of model based on the model_category just obtained and stuff the
        # new object into `self._fitted_model`.

        # There is no additional packaging of the model at this point. This builder is
        # responsible for is passing the raw output to the correct model category class
        # and then call its "new", which does all of the necessary manufacturing of the
        # model (i.e. mines the raw output suitable for showing, summarizing, predicting,
        # plotting, and deriving model metrics).

        # BINOMIAL model
        if self._model_type == self.BINOMIAL:
            self._fitted_model = H2OBinomialModel(model["output"], algo=self._algo)

        # MULTINOMIAL model
        elif self._model_type == self.MULTINOMIAL:
            self._fitted_model = H2OMultinomialModel(model["output"], algo=self._algo)

        # CLUSTERING model
        elif self._model_type == self.CLUSTERING:
            self._fitted_model = H2OClusteringModel(model["output"], algo=self._algo)

        # REGRESSION model
        elif self._model_type == self.REGRESSION:
            self._fitted_model = H2ORegressionModel(model["output"], algo=self._algo)

        else:
            raise H2OUnknownModelError("Don't know what to do with model type: "
                                       + self._model_type)

        self._fitted_model._key = destination_key
