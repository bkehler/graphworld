import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor
from typing import Optional, Tuple
import scipy as sp
import scipy.sparse as sprs
import scipy.spatial
import scipy.sparse.linalg

# Copied from https://github.com/Namkyeong/BGRL_Pytorch
class EMA:
    def __init__(self, beta, epochs):
        super().__init__()
        self.beta = beta
        self.step = 0
        self.total_steps = epochs

    def update_average(self, old, new):
        if old is None:
            return new
        beta = 1 - (1 - self.beta) * (np.cos(np.pi * self.step / self.total_steps) + 1) / 2.0
        self.step += 1
        return old * beta + (1 - beta) * new
    

def init_weights(m):
        if type(m) == torch.nn.Linear:
            torch.nn.init.xavier_uniform_(m.weight)
            if m.bias is not None:
                m.bias.data.fill_(0.01)

def pad_views(view1data, view2data):
        diff = abs(view2data.x.shape[1] - view1data.x.shape[1])
        if diff > 0:
            smaller_data = view1data if view1data.x.shape[1] < view2data.x.shape[1] else view2data
            smaller_data.x = F.pad(smaller_data.x, pad=(0, diff))
            view1data.x = F.normalize(view1data.x)
            view2data.x = F.normalize(view2data.x)


def compute_InfoNCE_loss(z1: Tensor, z2: Tensor, tau: float = 1.0):
    z1 = F.normalize(z1)
    z2 = F.normalize(z2)

    refl_sim = torch.exp(torch.mm(z1, z1.t()) / tau) # inter-view
    between_sim = torch.exp(torch.mm(z1, z2.t()) / tau) # intra-view

    return -torch.log(
        between_sim.diag() / (refl_sim.sum(1) + between_sim.sum(1) - refl_sim.diag())
    )





def pagerank(A, p=0.85,
             personalize=None, reverse=False):
    """ Calculates PageRank given a csr graph
    Inputs:
    -------
    G: a csr graph.
    p: damping factor
    personlize: if not None, should be an array with the size of the nodes
                containing probability distributions.
                It will be normalized automatically
    reverse: If true, returns the reversed-PageRank
    outputs
    -------
    PageRank Scores for the nodes
    """
    # In Moler's algorithm, $A_{ij}$ represents the existences of an edge
    # from node $j$ to $i$, while we have assumed the opposite!
    if reverse:
        A = A.T

    n, _ = A.shape
    r = sp.asarray(A.sum(axis=1)).reshape(-1)

    k = r.nonzero()[0]

    D_1 = sprs.csr_matrix((1 / r[k], (k, k)), shape=(n, n))

    if personalize is None:
        personalize = sp.ones(n)
    personalize = personalize.reshape(n, 1)
    s = (personalize / personalize.sum()) * n

    I = sprs.eye(n)
    x = sprs.linalg.spsolve((I - p * A.T @ D_1), s)

    x = x / x.sum()
    return x


def pagerank_power(A, p=0.85, max_iter=100,
                   tol=1e-06, personalize=None, reverse=False):
    """ Calculates PageRank given a csr graph
    Inputs:
    -------
    A: a csr graph.
    p: damping factor
    max_iter: maximum number of iterations
    personlize: if not None, should be an array with the size of the nodes
                containing probability distributions.
                It will be normalized automatically.
    reverse: If true, returns the reversed-PageRank
    Returns:
    --------
    PageRank Scores for the nodes
    """
    # In Moler's algorithm, $G_{ij}$ represents the existences of an edge
    # from node $j$ to $i$, while we have assumed the opposite!
    if reverse:
        A = A.T

    n, _ = A.shape
    r = sp.asarray(A.sum(axis=1)).reshape(-1)

    k = r.nonzero()[0]

    D_1 = sprs.csr_matrix((1 / r[k], (k, k)), shape=(n, n))

    if personalize is None:
        personalize = sp.ones(n)
    personalize = personalize.reshape(n, 1)
    s = (personalize / personalize.sum()) * n

    z_T = (((1 - p) * (r != 0) + (r == 0)) / n)[sp.newaxis, :]
    W = p * A.T @ D_1

    x = s
    oldx = sp.zeros((n, 1))

    iteration = 0

    while sp.linalg.norm(x - oldx) > tol:
        oldx = x
        x = W @ x + s @ (z_T @ x)
        iteration += 1
        if iteration >= max_iter:
            break
    x = x / sum(x)

    return x.reshape(-1)




def _check_input(
    x: Tensor, y: Optional[Tensor] = None, zero_diagonal: Optional[bool] = None
) -> Tuple[Tensor, Tensor, bool]:
    """Check that input has the right dimensionality and sets the ``zero_diagonal`` argument if user has not
    provided import module.
    Args:
        x: tensor of shape ``[N,d]``
        y: if provided, a tensor of shape ``[M,d]``
        zero_diagonal: determines if the diagonal of the distance matrix should be set to zero
    """
    if x.ndim != 2:
        raise ValueError(f"Expected argument `x` to be a 2D tensor of shape `[N, d]` but got {x.shape}")

    if y is not None:
        if y.ndim != 2 or y.shape[1] != x.shape[1]:
            raise ValueError(
                "Expected argument `y` to be a 2D tensor of shape `[M, d]` where"
                " `d` should be same as the last dimension of `x`"
            )
        zero_diagonal = False if zero_diagonal is None else zero_diagonal
    else:
        y = x.clone()
        zero_diagonal = True if zero_diagonal is None else zero_diagonal
    return x, y, zero_diagonal


def _safe_matmul(x: Tensor, y: Tensor) -> Tensor:
    """Safe calculation of matrix multiplication.
    If input is float16, will cast to float32 for computation and back again.
    """
    if x.dtype == torch.float16 or y.dtype == torch.float16:
        return (x.float() @ y.T.float()).half()
    return x @ y.T


def pairwise_cosine_similarity(x: Tensor, y: Optional[Tensor] = None, zero_diagonal: Optional[bool] = None):
    x, y, zero_diagonal = _check_input(x, y, zero_diagonal)

    norm = torch.norm(x, p=2, dim=1)
    x = x / norm.unsqueeze(1)
    norm = torch.norm(y, p=2, dim=1)
    y = y / norm.unsqueeze(1)

    distance = _safe_matmul(x, y)
    if zero_diagonal:
        distance.fill_diagonal_(0)
    return distance