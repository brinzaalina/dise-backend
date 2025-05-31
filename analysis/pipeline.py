import logging
import pandas as pd
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
from .utils import DataLoadError

logger = logging.getLogger(__name__)


def compute_commit_statistics(commit_df: pd.DataFrame) -> (pd.DataFrame, pd.DataFrame):
    """
    Compute commit statistics from a DataFrame containing commit data.
    Args:
        commit_df (pd.DataFrame): DataFrame containing commit data with columns 'version' and 'ccs_type'.
    Returns:
        tuple: A tuple containing two DataFrames:
            - counts: DataFrame with counts of commits by version and ccs_type.
            - ratios: DataFrame with ratios of commit types by version.
    """
    logger.info("Computing commit statistics.")
    counts = commit_df.groupby(["version", "ccs_type"]).size().unstack(fill_value=0)
    counts["total_commits"] = counts.sum(axis=1)
    ratios = counts.div(counts["total_commits"], axis=0).add_suffix("_ratio")
    logger.info("Commit statistics computed successfully.")
    return counts, ratios


def prepare_features(
    metrics_df: pd.DataFrame, counts_df: pd.DataFrame, ratios_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Prepare the feature matrix by aligning versions across metrics, counts, and ratios DataFrames.
    Args:
        metrics_df (pd.DataFrame): DataFrame containing release metrics with versions as index.
        counts_df (pd.DataFrame): DataFrame containing commit counts with versions as index.
        ratios_df (pd.DataFrame): DataFrame containing commit ratios with versions as index.
    Returns:
        pd.DataFrame: A DataFrame containing the aligned feature matrix with versions as index.
    Raises:
        DataLoadError: If there are no common versions between metrics and commit statistics after normalization.
    """
    logger.info("Preparing feature matrix by aligning versions")
    common_versions = set(metrics_df.index).intersection(set(counts_df.index))
    if not common_versions:
        logger.error("No common versions found between metrics and commit statistics")
        raise DataLoadError(
            "No common versions found between metrics and commits after normalization"
        )

    def version_key(v):
        parts = [int(p) if p.isdigit() else p for p in v.split(".")]
        return parts

    common_sorted = sorted(common_versions, key=version_key)

    metrics_aligned = metrics_df.loc[common_sorted]
    counts_aligned = counts_df.loc[common_sorted]
    ratios_aligned = ratios_df.loc[common_sorted]

    features = metrics_aligned.join(counts_aligned).join(ratios_aligned).fillna(0)
    logger.info("Feature matrix prepared successfully with aligned versions.")
    return features


def cluster_features(features_df: pd.DataFrame, n_clusters: int = 4):
    """
    Cluster the features DataFrame using KMeans clustering.
    Args:
        features_df (pd.DataFrame): DataFrame containing the feature matrix with versions as index.
        n_clusters (int): Number of clusters to form.
    Returns:
        tuple: A tuple containing:
            - clustered_df: DataFrame with the original features and an additional 'cluster' column.
            - scaler: StandardScaler object used for scaling the features.
            - kmeans: KMeans object fitted to the scaled features.
    """
    logger.info(
        f"Clustering {features_df.shape[0]} releases into {n_clusters} clusters"
    )
    X = features_df.values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    clusters = kmeans.fit_predict(X_scaled)

    clustered_df = features_df.copy()
    clustered_df["cluster"] = clusters
    return clustered_df, scaler, kmeans


def compute_pca_loadings(
    features_df: pd.DataFrame, scaler: StandardScaler
) -> pd.DataFrame:
    """
    Compute PCA loadings for the first two principal components from the features DataFrame.
    Args:
        features_df (pd.DataFrame): DataFrame containing the feature matrix with versions as index.
        scaler (StandardScaler): StandardScaler object used for scaling the features.
    Returns:
        pd.DataFrame: DataFrame containing the PCA loadings for PC1 and PC2.
    """
    logger.info("Computing PCA loadings for PC1 and PC2")
    X = features_df.values
    X_scaled = scaler.transform(X)
    pca = PCA(n_components=2)
    pca.fit(X_scaled)

    loadings = pd.DataFrame(
        pca.components_.T, index=features_df.columns, columns=["PC1", "PC2"]
    )
    logger.info("PCA loadings computed successfully.")
    return loadings


def summarize_clusters(clustered_df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarize cluster profiles by computing the mean feature values for each cluster.
    Args:
        clustered_df (pd.DataFrame): DataFrame containing the clustered features with a 'cluster' column.
    Returns:
        pd.DataFrame: DataFrame containing the mean feature values for each cluster.
    """
    logger.info("Summarizing cluster profiles (mean feature values)")
    feature_cols = [c for c in clustered_df.columns if c != "cluster"]
    profiles = clustered_df.groupby("cluster")[feature_cols].mean()
    logger.info("Cluster profiles summarized successfully.")
    return profiles


def compute_correlations(clustered_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute correlations between commit ratios and quality metrics in the clustered DataFrame.
    Args:
        clustered_df (pd.DataFrame): DataFrame containing the clustered features with commit ratios and quality metrics.
    Returns:
        pd.DataFrame: DataFrame containing the correlation coefficients between commit ratios and quality metrics.
    """
    logger.info("Computing correlations between commit ratios and quality metrics")
    commit_ratio_cols = [c for c in clustered_df.columns if c.endswith('_ratio')]
    metric_cols = [c for c in clustered_df.columns if (not c.endswith('_ratio') and c != 'cluster')]

    corr_df = clustered_df[commit_ratio_cols + metric_cols].corr().loc[commit_ratio_cols, metric_cols]
    logger.info("Correlations computed successfully.")
    return corr_df


def compute_pca_projection(clustered_df: pd.DataFrame, scaler: StandardScaler) -> pd.DataFrame:
    """
    Compute PCA projection for visualization from the clustered DataFrame.
    Args:
        clustered_df (pd.DataFrame): DataFrame containing the clustered features with a 'cluster' column.
        scaler (StandardScaler): StandardScaler object used for scaling the features.
    Returns:
        pd.DataFrame: DataFrame containing the PCA projection with columns 'PC1' and 'PC2'.
    """
    logger.info("Computing PCA projection (2D) for visualization")
    X = clustered_df.drop(columns='cluster').values
    X_scaled = scaler.transform(X)
    pca = PCA(n_components=2)
    proj = pca.fit_transform(X_scaled)
    proj_df = pd.DataFrame(proj, index=clustered_df.index, columns=["PC1", "PC2"])
    logger.info("PCA projection computed successfully.")
    return proj_df


def write_analysis_results(
    commits_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    excel_path: Path,
    png_path: Path,
    n_clusters: int = 3
) -> dict:
    """
    Run the full analysis pipeline:
      1. Compute commit counts/ratios
      2. Prepare features (intersect versions)
      3. Cluster releases
      4. Compute PCA loadings
      5. Summarize cluster profiles
      6. Compute correlations
      7. Write results to Excel (PCA_Loadings, Cluster_Profiles, Correlations, Clustered_Releases)
      8. Create and save PCA scatter plot to png_path
    Returns a dict containing all computed data for API responses.
    """
    # Step 1: compute commit stats
    counts_df, ratios_df = compute_commit_statistics(commits_df)
    # Step 2: prepare features
    features_df = prepare_features(metrics_df, counts_df, ratios_df)
    # Step 3: cluster
    clustered_df, scaler, kmeans = cluster_features(features_df, n_clusters)
    # Step 4: PCA loadings
    loadings_df = compute_pca_loadings(features_df, scaler)
    # Step 5: cluster profiles
    profiles_df = summarize_clusters(clustered_df)
    # Step 6: correlations
    corr_df = compute_correlations(clustered_df)
    # Step 7: write to Excel
    with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
        loadings_df.to_excel(writer, sheet_name='PCA_Loadings')
        profiles_df.to_excel(writer, sheet_name='Cluster_Profiles')
        corr_df.to_excel(writer, sheet_name='Correlations')
        clustered_df.to_excel(writer, sheet_name='Clustered_Releases')

    logger.info(f"Saved analysis results to Excel: {excel_path}")
    # Step 8: create scatter plot
    proj_df = compute_pca_projection(clustered_df, scaler)
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(proj_df['PC1'], proj_df['PC2'], c=clustered_df['cluster'], cmap='tab10', s=100)
    for i, version in enumerate(proj_df.index):
        ax.annotate(version, (proj_df.iloc[i, 0] + 0.02, proj_df.iloc[i, 1] + 0.02), fontsize=8)
    ax.set_title('Releases clustered by commit-type and quality metrics')
    ax.set_xlabel('PCA Component 1')
    ax.set_ylabel('PCA Component 2')
    ax.grid(True)
    plt.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)
    logger.info(f"Saved PCA scatter plot to PNG: {png_path}")

    # Build return dictionary
    releases_list = list(features_df.index)
    commit_stats = counts_df.loc[releases_list].to_dict(orient='index')
    commit_ratios = ratios_df.loc[releases_list].to_dict(orient='index')
    quality_metrics = metrics_df.loc[releases_list].to_dict(orient='index')
    cluster_assignment = clustered_df['cluster'].astype(int).to_dict()
    pca_loadings = loadings_df.round(3).to_dict(orient='index')
    cluster_profiles = profiles_df.round(3).to_dict(orient='index')
    correlations = corr_df.round(3).to_dict(orient='index')
    pca_projection = proj_df.round(3).to_dict(orient='index')

    result = {
        'releases': releases_list,
        'commit_stats': commit_stats,
        'commit_ratios': commit_ratios,
        'quality_metrics': quality_metrics,
        'cluster_assignment': cluster_assignment,
        'pca_loadings': pca_loadings,
        'cluster_profiles': cluster_profiles,
        'correlations': correlations,
        'pca_projection': pca_projection
    }
    return result