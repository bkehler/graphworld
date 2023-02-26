from torch.nn import Linear
from sklearn.decomposition import PCA
import numpy as np
import torch
import torch.nn.functional as F
import gin
from abc import ABC, abstractclassmethod
from dataclasses import dataclass
from __types import *

class BasicPretextTask(ABC):
    def __init__(self, data, encoder, train_mask, **kwargs): # **kwargs is needed
        self.data = data.clone()
        self.encoder = encoder
        self.train_mask = train_mask
        self.decoder = None

    # Override this function to return the pretext task loss
    # The embeddings for the downstream task is given, to be used
    # when the input graph is the same for downstream/pretext tasks
    @abstractclassmethod
    def make_loss(self, embeddings):
        pass



# ============================================ #
# ============= Generation-based ============= # 
# ============================================ #

# ------------- Feature generation ------------- #
@gin.configurable
class AttributeMask(BasicPretextTask):
    def __init__(self, node_mask_ratio=0.1, **kwargs):
        super().__init__(**kwargs)

        # Crea mask of subset of unlabeled nodes
        all = np.arange(self.data.x.shape[0])
        unlabeled = all[~self.train_mask]
        perm = np.random.permutation(unlabeled)
        self.masked_nodes = perm[: int(len(perm)*node_mask_ratio)]

        # Generate pseudo labels and mask input features
        # We employ PCA to pseudo labels/predictions
        # if features are high-dimensional
        self.pseudo_labels = self.data.x.clone()
        self.data.x[self.masked_nodes] = torch.zeros(self.data.x.shape[1])
        if self.pseudo_labels.shape[1] > 256:
            pca = PCA(n_components=256)
            self.pseudo_labels = pca.fit_transform(self.pseudo_labels)
        self.pseudo_labels = torch.FloatTensor(self.pseudo_labels[self.masked_nodes]).float()

        # Specify pretext decoder
        self.decoder = Linear(self.encoder.out_channels, self.pseudo_labels.shape[1])

    # Run masked input through graph encoder instead of using the original embeddings
    def make_loss(self, embeddings):
        z = self.encoder(self.data.x, self.data.edge_index)
        y_hat = (self.decoder(z[self.masked_nodes]))
        loss = F.mse_loss(y_hat, self.pseudo_labels, reduction='mean')
        return loss


@gin.configurable
class CorruptedFeaturesReconstruction(BasicPretextTask):
    def __init__(self, feature_corruption_ratio = 0.1, 
                 partial_feature_reconstruction=True, **kwargs):
        super().__init__(**kwargs)

        # Create Mask of subset of feature columns
        f_cols = np.arange(self.data.x.shape[1])
        perm = np.random.permutation(f_cols)
        masked_f_cols = perm[: int(len(perm)*feature_corruption_ratio)]

        # Create pseudo labels
        self.pseudo_labels = self.data.x.clone()
        if partial_feature_reconstruction:
            self.pseudo_labels = self.pseudo_labels[:, masked_f_cols]

         # Mask input features
        self.data.x[:,masked_f_cols] = 0

         # Specify pretext decoder
        self.decoder = Linear(self.encoder.out_channels, self.pseudo_labels.shape[1])

    # Run masked input through graph encoder instead of using the original embeddings
    def make_loss(self, embeddings):
        z = self.encoder(self.data.x, self.data.edge_index)
        y_hat = (self.decoder(z))
        loss = F.mse_loss(y_hat, self.pseudo_labels, reduction='mean')
        return loss
    

@gin.configurable
class CorruptedEmbeddingsReconstruction(BasicPretextTask):
    def __init__(self, embedding_corruption_ratio = 0.1, 
                 partial_embedding_reconstruction=True, **kwargs):
        super().__init__(**kwargs)

        self.partial_embedding_reconstruction = partial_embedding_reconstruction

        # Create Mask of subset of embedding columns
        embedding_cols = np.arange(self.encoder.out_channels)
        perm = np.random.permutation(embedding_cols) # Likely not needed
        self.masked_embedding_cols = perm[: int(len(perm)*embedding_corruption_ratio)]
        self.mask = torch.eye(self.encoder.out_channels)
        self.mask[self.masked_embedding_cols, self.masked_embedding_cols] = 0

        # Specify pretext decoder
        out = len(self.masked_embedding_cols) if partial_embedding_reconstruction else self.encoder.out_channels
        self.decoder = Linear(self.encoder.out_channels, out)

    # Mask embeddings and reconstruct with decoder
    def make_loss(self, embeddings):
        masked_embeddings = torch.matmul(embeddings, self.mask)
        y_hat = (self.decoder(masked_embeddings))
        if self.partial_embedding_reconstruction:
            pseudo_labels = embeddings[:, self.masked_embedding_cols]
        else:
            pseudo_labels = embeddings
        return F.mse_loss(y_hat, pseudo_labels, reduction='mean')





# ------------- Structure generation ------------- #


# ==================================================== #
# ============= Auxiliary property-based ============= # 
# ==================================================== #
