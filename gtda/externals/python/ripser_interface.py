import gc
from warnings import warn

import numpy as np
from scipy import sparse
from scipy.spatial.distance import squareform
from sklearn.metrics.pairwise import pairwise_distances

from ..modules import gtda_ripser, gtda_ripser_coeff, gtda_collapser


def _lexsort_coo_data(row, col, data):
    lex_sort_idx = np.lexsort((col, row))
    row, col, data = \
        row[lex_sort_idx], col[lex_sort_idx], data[lex_sort_idx]
    return row, col, data


def DRFDM(DParam, maxHomDim, thresh=-1, coeff=2, do_cocycles=0):
    if coeff == 2:
        ret = gtda_ripser.rips_dm(DParam, DParam.shape[0], coeff, maxHomDim,
                                  thresh, do_cocycles)
    else:
        ret = gtda_ripser_coeff.rips_dm(DParam, DParam.shape[0], coeff,
                                        maxHomDim, thresh, do_cocycles)
    return ret


def DRFDMSparse(I, J, V, N, maxHomDim, thresh=-1, coeff=2, do_cocycles=0):
    if coeff == 2:
        ret = gtda_ripser.rips_dm_sparse(I, J, V, I.size, N, coeff, maxHomDim,
                                         thresh, do_cocycles)
    else:
        ret = gtda_ripser_coeff.rips_dm_sparse(I, J, V, I.size, N, coeff,
                                               maxHomDim, thresh, do_cocycles)
    return ret


def dpoint2pointcloud(X, i, metric):
    """Return the distance from the ith point in a Euclidean point cloud
    to the rest of the points.

    Parameters
    ----------
    X: ndarray (n_samples, n_features)
        A numpy array of data

    i: int
        The index of the point from which to return all distances

    metric: string or callable
        The metric to use when calculating distance between instances in a
        feature array

    """
    ds = pairwise_distances(X, X[i, :][None, :], metric=metric).flatten()
    ds[i] = 0
    return ds


def get_greedy_perm(X, n_perm=None, metric="euclidean"):
    """Compute a furthest point sampling permutation of a set of points

    Parameters
    ----------
    X: ndarray (n_samples, n_features)
        A numpy array of either data or distance matrix

    n_perm: int
        Number of points to take in the permutation

    metric: string or callable
        The metric to use when calculating distance between instances in a
        feature array

    Returns
    -------
    idx_perm: ndarray(n_perm)
        Indices of points in the greedy permutation

    lambdas: ndarray(n_perm)
        Covering radii at different points

    dperm2all: ndarray(n_perm, n_samples)
        Distances from points in the greedy permutation to points
        in the original point set

    """
    if not n_perm:
        n_perm = X.shape[0]
    # By default, takes the first point in the list to be the
    # first point in the permutation, but could be random
    idx_perm = np.zeros(n_perm, dtype=np.int64)
    lambdas = np.zeros(n_perm)
    if metric == 'precomputed':
        dpoint2all = lambda i: X[i, :]
    else:
        dpoint2all = lambda i: dpoint2pointcloud(X, i, metric)
    ds = dpoint2all(0)
    dperm2all = [ds]
    for i in range(1, n_perm):
        idx = np.argmax(ds)
        idx_perm[i] = idx
        lambdas[i - 1] = ds[idx]
        dperm2all.append(dpoint2all(idx))
        ds = np.minimum(ds, dperm2all[-1])
    lambdas[-1] = np.max(ds)
    dperm2all = np.array(dperm2all)
    return idx_perm, lambdas, dperm2all


def ripser(X, maxdim=1, thresh=np.inf, coeff=2, metric="euclidean",
           n_perm=None, collapse_edges=False):
    """Compute persistence diagrams for X data array using Ripser [1]_.

    If X is not a distance matrix, it will be converted to a distance matrix
    using the chosen metric.

    Parameters
    ----------
    X : ndarray of shape (n_samples, n_features)
        A numpy array of either data or distance matrix. Can also be a sparse
        distance matrix of type scipy.sparse

    maxdim : int, optional, default: ``1``
        Maximum homology dimension computed. Will compute all dimensions lower
        than and equal to this value. For 1, H_0 and H_1 will be computed.

    thresh : float, optional, default: ``numpy.inf``
        Maximum distances considered when constructing filtration. If
        ``numpy.inf``, compute the entire filtration.

    coeff : int prime, optional, default: ``2``
        Compute homology with coefficients in the prime field Z/pZ for p=coeff.

    metric : string or callable, optional, default: ``'euclidean'``
        The metric to use when calculating distance between instances in a
        feature array. If set to ``'precomputed'``, input data is interpreted
        as a distance matrix or of adjacency matrices of a weighted undirected
        graph. If a string, it must be one of the options allowed by
        :func:`scipy.spatial.distance.pdist` for its metric parameter, or a
        or a metric listed in
        :obj:`sklearn.pairwise.PAIRWISE_DISTANCE_FUNCTIONS`, including
        ``'euclidean'``, ``'manhattan'`` or ``'cosine'``. If a callable, it
        should take pairs of vectors (1D arrays) as input and, for each two
        vectors in a pair, it should return a scalar indicating the
        distance/dissimilarity between them.

    n_perm : int or None, optional, default: ``None``
        The number of points to subsample in a "greedy permutation", or a
        furthest point sampling of the points. These points will be used in
        lieu of the full point cloud for a faster computation, at the expense
        of some accuracy, which can be bounded as a maximum bottleneck distance
        to all diagrams on the original point set.

    collapse_edges : bool, optional, default: ``False``
        Whether to use the edge collapse algorithm as described in [2]_ prior
        to calling ``ripser``.

    Returns
    -------
    A dictionary holding all of the results of the computation
    {
        'dgms': list (size maxdim) of ndarray (n_pairs, 2)
            A list of persistence diagrams, one for each dimension less
            than maxdim. Each diagram is an ndarray of size (n_pairs, 2)
            with the first column representing the birth time and the
            second column representing the death time of each pair.
        'num_edges': int
            The number of edges added during the computation
        'dperm2all': None or ndarray (n_perm, n_samples)
            ``None`` if n_perm is ``None``. Otherwise, the distance from all
            points in the permutation to all points in the dataset.
        'idx_perm': ndarray(n_perm) if n_perm > 0
            Index into the original point cloud of the points used
            as a subsample in the greedy permutation
        'r_cover': float
            Covering radius of the subsampled points.
            If n_perm <= 0, then the full point cloud was used and this is 0
    }

    Notes
    -----
    `Ripser <https://github.com/Ripser/ripser>`_ is used as a C++ backend
    for computing Vietoris–Rips persistent homology. Python bindings were
    modified for performance from the `ripser.py
    <https://github.com/scikit-tda/ripser.py>`_ package.

    `GUDHI <https://github.com/GUDHI/gudhi-devel>`_ is used as a C++ backend
    for the edge collapse algorithm described in [2]_.

    References
    ----------
    .. [1] U. Bauer, "Ripser: efficient computation of Vietoris–Rips
           persistence barcodes", 2019; `arXiv:1908.02518
           <https://arxiv.org/abs/1908.02518>`_.

    .. [2] J.-D. Boissonnat and S. Pritam, "Edge Collapse and Persistence of
           Flag Complexes"; in *36th International Symposium on Computational
           Geometry (SoCG 2020)*, pp. 19:1–19:15, Schloss
           Dagstuhl-Leibniz–Zentrum für Informatik, 2020;
           `DOI: 10.4230/LIPIcs.SoCG.2020.19
           <https://doi.org/10.4230/LIPIcs.SoCG.2020.19>`_.

    """
    if n_perm and sparse.issparse(X):
        raise Exception(
            "Greedy permutation is not supported for sparse distance matrices"
        )
    if n_perm and n_perm > X.shape[0]:
        raise Exception(
            "Number of points in greedy permutation is greater"
            " than number of points in the point cloud"
        )
    if n_perm and n_perm < 0:
        raise Exception(
            "Should be a strictly positive number of points in the greedy "
            "permutation"
        )

    idx_perm = np.arange(X.shape[0])
    r_cover = 0.0
    if n_perm:
        idx_perm, lambdas, dperm2all = get_greedy_perm(
            X, n_perm=n_perm, metric=metric
        )
        r_cover = lambdas[-1]
        dm = dperm2all[:, idx_perm]
    else:
        if metric == 'precomputed':
            dm = X
        else:
            dm = pairwise_distances(X, metric=metric)
        dperm2all = None

    n_points = max(dm.shape)
    sort_coo = True
    if (dm.diagonal() != 0).any():
        if collapse_edges:
            warn("Edge collapses are not supported when any of the diagonal "
                 "entries are non-zero. Computing persistent homology without "
                 "using edge collapse.")
            collapse_edges = False
        if not sparse.issparse(dm):
            # If any of the diagonal elements are nonzero, convert to sparse
            # format, because currently that's the only format that handles
            # nonzero births
            dm = sparse.coo_matrix(dm)
            sort_coo = False

    if sparse.issparse(dm) or collapse_edges:
        if collapse_edges:
            sort_coo = True
            if not sparse.issparse(dm):
                row, col, data = \
                    gtda_collapser.flag_complex_collapse_edges_dense(dm,
                                                                     thresh)
            else:
                coo = dm.tocoo()
                row, col, data = \
                    gtda_collapser.flag_complex_collapse_edges_coo(coo.row,
                                                                   coo.col,
                                                                   coo.data,
                                                                   thresh)
        else:
            if sparse.isspmatrix_coo(dm):
                # If the matrix is already COO, we need to order the row and
                # column indices lexicographically to avoid errors. See
                # https://github.com/scikit-tda/ripser.py/issues/103
                row, col, data = dm.row, dm.col, dm.data
            else:
                coo = dm.tocoo()
                row, col, data = coo.row, coo.col, coo.data
                sort_coo = False

        if sort_coo:
            row, col, data = _lexsort_coo_data(np.asarray(row),
                                               np.asarray(col),
                                               np.asarray(data))

        res = DRFDMSparse(
            row.astype(dtype=np.int32, order="C"),
            col.astype(dtype=np.int32, order="C"),
            np.array(data, dtype=np.float32, order="C"),
            n_points,
            maxdim,
            thresh,
            coeff
            )
    else:
        # Only consider strict upper diagonal
        DParam = squareform(dm, checks=False).astype(np.float32)
        # Run garbage collector to free up memory taken by `dm`
        del dm
        gc.collect()
        res = DRFDM(DParam, maxdim, thresh, coeff)

    # Unwrap persistence diagrams
    dgms = res.births_and_deaths_by_dim
    for dim in range(len(dgms)):
        N = int(len(dgms[dim]) / 2)
        dgms[dim] = np.reshape(np.array(dgms[dim]), [N, 2])

    ret = {
        "dgms": dgms,
        "num_edges": res.num_edges,
        "dperm2all": dperm2all,
        "idx_perm": idx_perm,
        "r_cover": r_cover,
    }
    return ret
