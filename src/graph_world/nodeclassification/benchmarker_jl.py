# Copyright 2022 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
There are currently 3 pieces required for each model:

  * BenchmarkerWrapper (ex. NodeGCN) -- Used in GIN config, this delegates to the Benchmarker.
  * ModelBenchmarker (ex. GCNNodeBenchmarker) -- This performs the actual training and eval steps for the model
  * Modelmpl (ex. GCNNodeModel) -- This is the actual model implemention (wrapping together convolution layers)
"""
import copy
import gin
import logging
import numpy as np
#import graph_tool.all as gt
from sklearn.linear_model import LinearRegression
import sklearn.metrics
import torch

from ..models.models import PyGBasicGraphModel
from ..beam.benchmarker import Benchmarker, BenchmarkerWrapper


class NNNodeBenchmarkerJL(Benchmarker):
  def __init__(self, generator_config, model_class, benchmark_params, h_params):
    super().__init__(generator_config, model_class, benchmark_params, h_params)
    # remove meta entries from h_params
    self._epochs = benchmark_params['epochs']

    self._model = model_class(**h_params)
    # TODO(palowitch): make optimizer configurable.
    self._optimizer = torch.optim.Adam(self._model.parameters(),
                                       lr=benchmark_params['lr'],
                                       weight_decay=5e-4)
    self._criterion = torch.nn.CrossEntropyLoss()
    self._train_mask = None
    self._val_mask = None
    self._test_mask = None

  def AdjustParams(self, generator_config):
    if 'num_clusters' in generator_config and self._h_params is not None:
      self._h_params['out_channels'] = generator_config['num_clusters']

  def SetMasks(self, train_mask, val_mask, test_mask):
    self._train_mask = train_mask
    self._val_mask = val_mask
    self._test_mask = test_mask

  def train_step(self, data):
    self._model.train()
    self._optimizer.zero_grad()  # Clear gradients.
    out = self._model(data.x, data.edge_index)  # Perform a single forward pass.
    loss = self._criterion(out[self._train_mask],
                           data.y[self._train_mask])  # Compute the loss solely based on the training nodes.
    loss.backward()  # Derive gradients.
    self._optimizer.step()  # Update parameters based on gradients.
    return loss

  def test(self, data, test_on_val=False):
    self._model.eval()
    out = self._model(data.x, data.edge_index)
    if test_on_val:
      pred = out[self._val_mask].detach().numpy()
    else:
      pred = out[self._test_mask].detach().numpy()

    pred_best = pred.argmax(-1)
    if test_on_val:
      correct = data.y[self._val_mask].numpy()
    else:
      correct = data.y[self._test_mask].numpy()
    n_classes = out.shape[-1]
    pred_onehot = np.zeros((len(pred_best), n_classes))
    pred_onehot[np.arange(pred_best.shape[0]), pred_best] = 1

    correct_onehot = np.zeros((len(correct), n_classes))
    correct_onehot[np.arange(correct.shape[0]), correct] = 1

    results = {
        'accuracy': sklearn.metrics.accuracy_score(correct, pred_best),
        'f1_micro': sklearn.metrics.f1_score(correct, pred_best,
                                                  average='micro'),
        'f1_macro': sklearn.metrics.f1_score(correct, pred_best,
                                                  average='macro'),
        'rocauc_ovr': sklearn.metrics.roc_auc_score(correct_onehot,
                                                         pred_onehot,
                                                         multi_class='ovr'),
        'rocauc_ovo': sklearn.metrics.roc_auc_score(correct_onehot,
                                                         pred_onehot,
                                                         multi_class='ovo'),
        'logloss': sklearn.metrics.log_loss(correct, pred)}
    return results

  def train(self, data,
            tuning_metric: str,
            tuning_metric_is_loss: bool):
    losses = []
    best_val_metric = np.inf if tuning_metric_is_loss else -np.inf
    test_metrics = None
    best_val_metrics = None
    for i in range(self._epochs):
      losses.append(float(self.train_step(data)))
      val_metrics = self.test(data, test_on_val=True)
      if ((tuning_metric_is_loss and val_metrics[tuning_metric] < best_val_metric) or
          (not tuning_metric_is_loss and val_metrics[tuning_metric] > best_val_metric)):
        best_val_metric = val_metrics[tuning_metric]
        best_val_metrics = copy.deepcopy(val_metrics)
        test_metrics = self.test(data, test_on_val=False)
    return losses, test_metrics, best_val_metrics

  def Benchmark(self, element,
                tuning_metric: str = None,
                tuning_metric_is_loss: bool = False):
    torch_data = element['torch_data']
    masks = element['masks']
    skipped = element['skipped']
    sample_id = element['sample_id']

    out = {
      'skipped': skipped,
      'results': None
    }
    out.update(element)
    out['losses'] = None
    out['val_metrics'] = {}
    out['test_metrics'] = {}

    if skipped:
      logging.info(f'Skipping benchmark for sample id {sample_id}')
      return out

    train_mask, val_mask, test_mask = masks

    self.SetMasks(train_mask, val_mask, test_mask)

    val_metrics = {}
    test_metrics = {}
    losses = None
    try:
      losses, test_metrics, val_metrics = self.train(
        torch_data, tuning_metric=tuning_metric, tuning_metric_is_loss=tuning_metric_is_loss)
    except Exception as e:
      logging.info(f'Failed to run for sample id {sample_id}')
      out['skipped'] = True

    out['losses'] = losses
    out['test_metrics'].update(test_metrics)
    out['val_metrics'].update(val_metrics)
    return out


@gin.configurable
class NNNodeBenchmarkJL(BenchmarkerWrapper):

  def GetBenchmarker(self):
    return NNNodeBenchmarkerJL(self._model_class, self._benchmark_params, self._h_params)

  def GetBenchmarkerClass(self):
    return NNNodeBenchmarkerJL