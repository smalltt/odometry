import mlflow
from functools import partial
from collections.abc import Iterable

import tensorflow as tf
import keras
from keras.layers import Input
from keras.models import Model, load_model
from keras.optimizers import Adam
from keras.utils.layer_utils import count_params

from slam.models.losses import (mean_squared_error,
                                mean_absolute_error,
                                mean_squared_logarithmic_error,
                                mean_squared_signed_logarithmic_error,
                                confidence_error,
                                rmse,
                                smooth_L1)
from slam.models.layers import CUSTOM_LAYERS
from slam.utils import mlflow_logging


class BaseModelFactory:
    def construct(self):
        raise NotImplementedError


class PretrainedModelFactory(BaseModelFactory):

    @mlflow_logging(ignore=(), prefix='model_factory.')
    def __init__(self, pretrained_path):
        self.pretrained_path = pretrained_path
        self.model = None

    def construct(self):
        sess = tf.Session()
        keras.backend.set_session(sess)
        with sess.as_default():
            custom_objects={'mean_squared_error': mean_squared_error,
                            'mean_absolute_error': mean_absolute_error,
                            'mean_squared_logarithmic_error': mean_squared_logarithmic_error,
                            'smooth_L1': smooth_L1,
                            'flow_loss': mean_squared_logarithmic_error,
                            'confidence_error': confidence_error,
                            'rmse': rmse,
                            **CUSTOM_LAYERS}
            self.model = load_model(self.pretrained_path, custom_objects=custom_objects)
        return self.model


class ModelFactory:

    @mlflow_logging(ignore=('construct_graph_fn',), prefix='model_factory.')
    def __init__(self,
                 construct_graph_fn,
                 input_shapes=((60, 80, 3), (60, 80, 3)),
                 lr=0.001,
                 loss=mean_squared_error,
                 scale_rotation=1.,
                 scale_translation=1.,
                 optimizer='adam'):
        self.model = None
        self.construct_graph_fn = construct_graph_fn
        self.input_shapes = input_shapes
        self.lr = lr
        self.optimizer = optimizer
        self.loss_fn = self._get_loss_function(loss)
        self.loss = [self.loss_fn] * 6
        if not isinstance(scale_rotation, Iterable):
            scale_rotation = [scale_rotation] * 3
        if not isinstance(scale_translation, Iterable):
            scale_translation = [scale_translation] * 3
        self.loss_weights = list(scale_rotation) + list(scale_translation)
        self.metrics = dict(zip(('euler_x', 'euler_y', 'euler_z', 't_x', 't_y', 't_z'), [rmse] * 6))

    def _get_optimizer(self):
        if self.optimizer == 'adam':
            return Adam(lr=self.lr, amsgrad=True)
        else:
            raise ValueError(f'Unknown optimizer: {self.optimizer}')

    @staticmethod
    def _get_loss_function(loss):
        if isinstance(loss, str):
            loss = loss.lower()
            if loss in ('mse', 'mean_squared_error'):
                return mean_squared_error
            if loss in ('mae', 'mean_absolute_error'):
                return mean_absolute_error
            if loss in ('msle', 'mean_squared_logarithmic_error'):
                return mean_squared_logarithmic_error
            if loss in ('mssle', 'mean_squared_signed_logarithmic_error'):
                return mean_squared_signed_logarithmic_error
            if loss in ('rmse', 'root_mean_squared_error'):
                return rmse
            if loss in ('huber', 'smoothl1', 'smooth_l1'):
                return smooth_L1
            if loss in ('confidence', 'confidence_error'):
                return confidence_error
        elif callable(loss):
            return loss
        else:
            raise ValueError

    def _compile(self):
        self.model.compile(loss=self.loss,
                           loss_weights=self.loss_weights,
                           optimizer=self._get_optimizer(),
                           metrics=self.metrics)

    def construct(self):
        inputs = [Input(input_shape) for input_shape in self.input_shapes]
        outputs = self.construct_graph_fn(inputs)
        self.model = Model(inputs=inputs, outputs=outputs)
        self._compile()

        if mlflow.active_run():
            mlflow.log_metric('num_of_parameters', count_params(self.model.trainable_weights))
        return self.model


class ModelWithDecoderFactory(ModelFactory):
    def __init__(self,
                 construct_graph_fn,
                 input_shapes=((60, 80, 3), (60, 80, 3)),
                 lr=0.001,
                 loss=mean_squared_error,
                 optim='adam',
                 scale_rotation=1.,
                 scale_translation=1.,
                 flow_loss_weight=1.,
                 flow_reconstruction_loss=mean_squared_logarithmic_error):
        super().__init__(construct_graph_fn=construct_graph_fn,
                         input_shapes=input_shapes,
                         lr=lr,
                         loss=loss,
                         optim=optim,
                         scale_rotation=scale_rotation,
                         scale_translation=scale_translation)
        self.loss.append(flow_reconstruction_loss)
        self.loss_weights.append(flow_loss_weight)


class ModelWithConfidenceFactory(ModelFactory):

    def __init__(self,
                 construct_graph_fn,
                 confidence_mode='log_std',
                 confidence_lr=0.001,
                 **kwargs):
        self.confidence_mode = confidence_mode
        self.confidence_lr = confidence_lr
        print(f'Confidence: mode={self.confidence_mode}, lr={self.confidence_lr}')
        mlflow.log_param('confidence_mode', self.confidence_mode)
        mlflow.log_param('confidence_lr', self.confidence_lr)

        super().__init__(construct_graph_fn=construct_graph_fn,
                         **kwargs)

    def freeze(self):
        for layer in self.model.layers:
            layer.trainable = not layer.trainable

        def confidence_loss(y_true, y_pred):
            return confidence_error(y_true, y_pred, mode=self.confidence_mode)

        self.loss = confidence_loss
        self.lr = self.confidence_lr
        self._compile()
        for layer in self.model.layers:
            print(f'{layer.name:<30} {layer.trainable}')
        return self.model
