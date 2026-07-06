import base64
import pandas as pd
import numpy as np
import os
import io
import json

import s3fs
from sklearn.preprocessing import StandardScaler
from scipy.signal import savgol_filter
from sqlalchemy import create_engine
from aiohttp import web



# ca = cache.CacheTools('seak8sm2.supcon5t.com', '30380', biz_type="tpt", model="run")


def data_quality_check(df, sampling_interval):
    """
    检查数据集的质量，返回数据集质量评分(0-2)，0为良好，1为数据集总天数小于90天，2为NaN值超过10%的列数大于2，3为其他情况

    参数:
    df - 数据处理完df，包含running_state列
    sampling_interval - 采样间隔(秒)

    返回:
    数据集质量评分(0-2)
    """

    ###########判断数据集的总天数###########
    # 保留 running_state != 0 的行
    df_filtered = df[df['running_state'] != 0]

    # 计算行数
    num_rows = len(df)

    # 计算总秒数
    total_seconds = num_rows * sampling_interval

    # 转换为天数
    total_days = total_seconds / 86400

    print(f"总天数: {total_days}")

    ###########判断nan值超过10%的列###########
    # 计算每列中 NaN 值的数量
    nan_counts = df.isna().sum()
    # 计算总行数
    total_rows = len(df)

    # 找出 NaN 值数量超过总行数 10% 的列
    columns_over_10_percent = nan_counts[nan_counts > total_rows * 0.1]

    # 统计这些列的数量
    num_columns_over_10_percent = len(columns_over_10_percent)

    print(f"NaN值数量超过总行数10%的列数: {num_columns_over_10_percent}")

    # 计算最大NaN值数量
    max_nan = nan_counts.max()
    print(f"最大NaN值数量: {max_nan}")

    if total_days < 90:
        tag = 1
        score = int(total_days / 90 * 100)
        print("数据集总天数小于90天，请检查数据质量")
    elif num_columns_over_10_percent > 2:
        tag = 2
        score = 50
        print("NaN值超过10%的列数大于2，请检查数据质量")
    else:
        tag = 0
        score = 90
        print("数据集质量良好")

    return tag, score, int(max_nan)


# 异常值处理
def process_outliers(df, window=3, iqr_factor=1.5, look_back=5, time_col='Timestamp'):
    """
    使用箱型图法(IQR)检测并处理DataFrame中的异常值，并用前后look_back个正常点的均值代替

    参数:
    df - 输入DataFrame，第一列作为时间列，其余作为特征列
    window - 连续异常值窗口大小(默认3)
    iqr_factor - IQR倍数(默认1.5)
    look_back - 用于计算均值的窗口大小(默认5)

    返回:
    处理后的DataFrame

    功能:
    1. 对特征列检测异常值(箱型图法)
    2. 处理异常值:
       - 单个或两个连续异常值: 用前后look_back个正常点的均值代替
       - 三个或更多连续异常值: 替换为NaN
    """
    try:
        if len(df.columns) < 2:
            raise ValueError("DataFrame必须至少包含两列(时间列+至少一个特征列)")

        processed_df = df.copy()
        # time_col = processed_df.columns[0]
        time_col = time_col
        time_data = processed_df[time_col]
        features = processed_df.drop(columns=[time_col])

        # for col in features.columns:
        #     data = features[col].copy()
        #
        #     # 计算Q1, Q3, IQR
        #     Q1 = data.quantile(0.25)
        #     Q3 = data.quantile(0.75)
        #     IQR = Q3 - Q1
        #
        #     # 计算上下界
        #     lower_bound = Q1 - iqr_factor * IQR
        #     upper_bound = Q3 + iqr_factor * IQR
        #
        #     # 检测异常值
        #     outliers = (data < lower_bound) | (data > upper_bound)
        #
        #     # 标记连续异常值组
        #     outlier_groups = outliers.ne(outliers.shift()).cumsum()
        #     counts = outliers.groupby(outlier_groups).transform('sum')
        #
        #     # 三个及以下连续异常值 - 用前后look_back个正常点的均值代替
        #     to_replace = outliers & (counts <= window)
        #     for idx in data.index[to_replace]:
        #         # 获取前后look_back个正常点
        #         start = max(0, idx - look_back)
        #         end = min(len(data), idx + look_back + 1)
        #         window_data = data[start:end][~outliers[start:end]]  # 只取正常点
        #         if len(window_data) > 0:
        #             data[idx] = window_data.mean()
        #         else:
        #             data[idx] = np.nan  # 如果没有正常点，设为NaN
        #
        #     # 大于连续异常值 - 替换为NaN
        #     to_nan = outliers & (counts > window)
        #     data[to_nan] = np.nan
        #
        #     features[col] = data
        #
        # processed_df = pd.concat([time_data, features], axis=1)
        return processed_df

    except Exception as e:
        print(f"处理过程中发生错误: {str(e)}")
        return None


# 缺失值处理
def handle_missing_values(df, time_col=None, window_size='30T', n_neighbors=5, debug=False):
    """
    最终有效版本，包含调试功能
    规则：
    1. 开头缺失 → 强制后向填充
    2. 末尾缺失 → 强制前向填充
    3. 中间缺失 → 前后各n个有效点的均值
    4. 不填充：
       - 连续超过3个缺失
       - 所在窗口(缺失点时间±15分钟)内缺失比例>1/3
    """
    df = df.copy()

    # 设置时间索引
    if time_col is not None:
        if time_col in df.columns:
            df[time_col] = pd.to_datetime(df[time_col])
            df.set_index(time_col, inplace=True)
        else:
            raise ValueError(f"时间列 '{time_col}' 不存在")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("索引必须是时间类型")

    for col in df.select_dtypes(include=[np.number]).columns:
        series = df[col].copy()
        is_na = series.isna()

        # ================= 步骤1：标记不填充区域 =================
        # 标记连续超过3个缺失
        na_groups = (is_na != is_na.shift()).cumsum()
        na_counts = is_na.groupby(na_groups).transform('sum')
        mask_over3 = (is_na) & (na_counts > 3)

        # 标记窗口内缺失>1/3的区域
        mask_window = pd.Series(False, index=series.index)
        for idx in np.where(is_na)[0]:
            center_time = series.index[idx]
            window_start = max(center_time - pd.Timedelta(window_size) / 2, series.index.min())
            window_end = min(center_time + pd.Timedelta(window_size) / 2, series.index.max())

            window = series.loc[window_start:window_end]
            if len(window) == 0 or window.isna().sum() > len(window) / 3:
                mask_window.iloc[idx] = True
                if debug:
                    print(f"标记不填充点 {center_time}，窗口内缺失比例 {window.isna().mean():.2f}")

        mask_no_fill = mask_over3 | mask_window

        # ================= 步骤2：执行填充 =================
        # 处理开头缺失（连续多个）
        first_valid = series.first_valid_index()
        if first_valid is not None:
            leading_na = series.index < first_valid
            series.loc[leading_na & ~mask_no_fill] = series.loc[first_valid]

        # 处理末尾缺失（连续多个）
        last_valid = series.last_valid_index()
        if last_valid is not None:
            trailing_na = series.index > last_valid
            series.loc[trailing_na & ~mask_no_fill] = series.loc[last_valid]

        # 处理中间缺失
        mid_na_mask = series.isna() & ~mask_no_fill
        for idx in np.where(mid_na_mask)[0]:
            # 查找前向有效值
            prev_values = []
            i = idx - 1
            while i >= 0 and len(prev_values) < n_neighbors:
                if not series.isna().iloc[i] and not mask_no_fill.iloc[i]:
                    prev_values.append(series.iloc[i])
                i -= 1

            # 查找后向有效值
            next_values = []
            i = idx + 1
            while i < len(series) and len(next_values) < n_neighbors:
                if not series.isna().iloc[i] and not mask_no_fill.iloc[i]:
                    next_values.append(series.iloc[i])
                i += 1

            # 计算填充值
            if prev_values or next_values:
                fill_value = np.nanmean(prev_values + next_values)  # 使用nanmean更安全
                if debug:
                    print(f"填充中间缺失 {series.index[idx]} 使用值 {fill_value:.2f}")
                series.iloc[idx] = fill_value

        df[col] = series

    if time_col is not None:
        df.reset_index(inplace=True)

    return df


def calculate_standardization_stats_all(df_raw, time_col, MV_col, sampling_interval):
    """
    计算DataFrame的标准化统计量;包含30s差值位号，MV重复位号30个

    参数:
        df_raw: 输入DataFrame，第一列为时间，其余列为特征
        time_col: 时间列名
        MV_col: MV列名

    返回:
        mean_df: 包含各特征均值的DataFrame(一行)
        std_df: 包含各特征标准差的DataFrame(一行)
    """
    df = df_raw.copy()

    # 获取所有列为 tag 的列名（即除时间列外的所有列）
    tag_names = df.drop(columns=[time_col]).columns.tolist()
    features = df[tag_names]

    # 计算间隔30秒需要几个点
    diff_interval = int(30 / sampling_interval)

    # 对每列计算隔两个点的差值，并新增_diff列
    for col in df[tag_names]:
        df[f'{col}_diff'] = df[col].diff(periods=diff_interval)

    # 重新提取特征列
    tag_names = df.drop(columns=[time_col]).columns.tolist()
    features = df[tag_names][diff_interval + 1:]

    # 初始化标准化器
    scaler = StandardScaler()

    # 计算标准化参数(此处不需要实际转换数据)
    scaler.fit(features)

    # 创建均值DataFrame(保留特征名作为列名)
    mean_df = pd.DataFrame([scaler.mean_], columns=tag_names)

    # 创建标准差DataFrame(保留特征名作为列名)
    std_df = pd.DataFrame([scaler.scale_], columns=tag_names)

    # 新加三十个MV列
    # 创建包含 30 个副本的新 DataFrame
    mean_new_cols = pd.concat([mean_df[MV_col] for _ in range(30)], axis=1)

    # 修改列名为 original_col_0 到 original_col_29
    mean_new_cols.columns = [f'{MV_col}_{i}' for i in range(30)]

    # 将新列合并回原 df（或新建一个 df）
    mean_new_df = pd.concat([mean_df, mean_new_cols], axis=1)

    # 创建包含 30 个副本的新 DataFrame
    std_new_cols = pd.concat([std_df[MV_col] for _ in range(30)], axis=1)

    # 修改列名为 original_col_0 到 original_col_29
    std_new_cols.columns = [f'{MV_col}_{i}' for i in range(30)]

    # 将新列合并回原 df（或新建一个 df）
    std_new_df = pd.concat([std_df, std_new_cols], axis=1)

    return mean_new_df, std_new_df


# 标准化
def calculate_standardization_stats(df):
    """
    计算DataFrame的标准化统计量

    参数:
        df: 输入DataFrame，第一列为时间，其余列为特征

    返回:
        mean_df: 包含各特征均值的DataFrame(一行)
        std_df: 包含各特征标准差的DataFrame(一行)
    """
    # 分离时间列和特征列
    features = df.iloc[:, 1:]
    tag_names = features.columns.tolist()  # 获取位号名列表

    # 初始化标准化器
    scaler = StandardScaler()

    # 计算标准化参数(此处不需要实际转换数据)
    scaler.fit(features)

    # 创建均值DataFrame(保留特征名作为列名)
    mean_df = pd.DataFrame([scaler.mean_], columns=tag_names)

    # 创建标准差DataFrame(保留特征名作为列名)
    std_df = pd.DataFrame([scaler.scale_], columns=tag_names)

    return mean_df, std_df


# 一阶滤波
def filter_dataframe(df, alpha=0.2, exclude_columns=None):
    """
    对 DataFrame 中的每一列进行一阶滤波，直接替换原始数据
    :param df: 输入的 DataFrame
    :param alpha: 滤波系数，0 < alpha <= 1
    :param exclude_columns: 需要排除的列名列表（默认为 None，表示不排除任何列）
    :return: 滤波后的 DataFrame（只包含滤波后的数据，保持原列名）
    """
    if exclude_columns is None:
        exclude_columns = []  # 如果没有指定排除列，则默认为空列表

    filtered_df = df.copy()  # 创建一个副本，避免修改原始 DataFrame

    def first_order_filter(signal):
        """
        内部函数：对信号进行一阶滤波
        """
        filtered_signal = np.full_like(signal, np.nan)  # 创建一个与输入信号相同形状的数组，初始值为 NaN
        last_valid_index = None  # 用于记录最后一个有效的滤波索引

        for i in range(len(signal)):
            if not np.isnan(signal[i]):  # 如果当前值不是 NaN
                if last_valid_index is None:  # 如果是第一个有效值
                    filtered_signal[i] = signal[i]  # 初始化滤波值
                else:
                    filtered_signal[i] = alpha * signal[i] + (1 - alpha) * filtered_signal[last_valid_index]
                last_valid_index = i  # 更新最后一个有效索引
        return filtered_signal

    for col in df.columns:
        if col not in exclude_columns:  # 跳过需要排除的列
            filtered_df[col] = first_order_filter(df[col].values)  # 直接替换原列数据

    return filtered_df


# 多项式滤波
def polynomial_filter_dataframe(df, degree=2, exclude_columns=None):
    """
    对 DataFrame 中的每一列进行多项式滤波，直接替换原始数据
    :param df: 输入的 DataFrame
    :param degree: 多项式的阶数
    :param exclude_columns: 需要排除的列名列表（默认为 None，表示不排除任何列）
    :return: 滤波后的 DataFrame（只包含滤波后的数据，保持原列名）
    """
    if exclude_columns is None:
        exclude_columns = []  # 如果没有指定排除列，则默认为空列表

    filtered_df = df.copy()  # 创建一个副本，避免修改原始 DataFrame

    for col in df.columns:
        if col not in exclude_columns:  # 跳过需要排除的列
            # 获取当前列的数据
            x = np.arange(len(df[col]))  # 假设 x 轴为索引
            y = df[col].values

            # 找出非 NaN 值的索引
            valid_indices = ~np.isnan(y)
            valid_x = x[valid_indices]
            valid_y = y[valid_indices]

            # 如果没有足够的数据点进行拟合，则保留原数据
            if len(valid_x) < degree + 1:
                continue  # 跳过该列，保持原数据不变

            # 对有效的数据点进行多项式拟合
            coeffs = np.polyfit(valid_x, valid_y, degree)
            poly = np.poly1d(coeffs)

            # 计算滤波后的值，仅对非 NaN 值进行计算
            filtered_values = np.full_like(y, np.nan)  # 初始化滤波结果为 NaN
            filtered_values[valid_indices] = poly(valid_x)

            # 直接替换原列数据
            filtered_df[col] = filtered_values

    return filtered_df


# Savitzky-Golay滤波
def savgol_filter_dataframe(df, window_length=15, polyorder=2, exclude_columns=None, **kwargs):
    """
    对DataFrame中的每一列进行Savitzky-Golay滤波（自动跳过NaN值），直接替换原始数据

    Parameters:
    -----------
    df : pd.DataFrame
        输入的DataFrame（允许包含NaN）
    window_length : int
        滤波窗口长度（必须为正奇数，默认15）
    polyorder : int
        多项式拟合阶数（必须小于window_length，默认2）
    exclude_columns : list, optional
        需要排除的列名列表（默认为None，表示不排除任何列）
    **kwargs :
        其他传递给scipy.signal.savgol_filter的参数（如deriv, delta, mode等）

    Returns:
    --------
    pd.DataFrame
        滤波后的DataFrame（保持原列名和结构，NaN位置不变）

    Example:
    --------
    # >>> df_smooth = savgol_filter_dataframe(
            df,
            window_length=17,
            polyorder=3,
            exclude_columns=['timestamp'],
            mode='nearest'
        )
    """
    if exclude_columns is None:
        exclude_columns = []

    # 参数校验
    if window_length % 2 != 1 or window_length <= 0:
        raise ValueError("window_length必须是正奇数")
    if polyorder >= window_length:
        raise ValueError("polyorder必须小于window_length")

    filtered_df = df.copy()  # 创建副本避免修改原数据

    def safe_savgol(signal, **kwargs):
        """处理带NaN的信号（严格模仿一阶滤波的NaN跳过逻辑）"""
        filtered = np.full_like(signal, np.nan)
        valid_idx = ~np.isnan(signal)  # 非NaN的索引

        if np.sum(valid_idx) >= window_length:  # 仅当有效数据足够时才滤波
            try:
                filtered[valid_idx] = savgol_filter(
                    signal[valid_idx],
                    window_length=min(window_length, np.sum(valid_idx)),  # 动态调整窗口避免过小
                    polyorder=min(polyorder, np.sum(valid_idx) - 1),  # 调整多项式阶数
                    **kwargs
                )
            except Exception as e:
                print(f"滤波失败: {str(e)}，返回原始值")
                filtered[valid_idx] = signal[valid_idx]  # 失败时回退
        else:
            filtered[valid_idx] = signal[valid_idx]  # 数据不足时保留原值

        return filtered

    for col in df.columns:
        if col not in exclude_columns and df[col].dtype.kind in 'fci':  # 仅处理数值列
            filtered_df[col] = safe_savgol(df[col].values, **kwargs)

    return filtered_df


def save_standardization_stats(base_path, mean_df, std_df):
    # 创建 S3 文件系统对象
    fs = s3fs.S3FileSystem()

    # 确保目录存在（S3 中其实是“模拟”创建）
    fs.makedirs(base_path, exist_ok=True)

    # 构建文件路径
    mean_path = os.path.join(base_path, 'pid_mean.csv')
    std_path = os.path.join(base_path, 'pid_std.csv')

    # 写入 mean.csv
    with fs.open(mean_path, 'w') as f:
        mean_df.to_csv(f, index=False)

    # 写入 std.csv
    with fs.open(std_path, 'w') as f:
        std_df.to_csv(f, index=False)

    print(f"标准化统计已成功保存至：{base_path}")


# 停车数据标注
def detect_and_clean_shutdown_data(
        df,
        timestamp_col='Timestamp',
        target_column='TE_02031.PV',
        window_size=1000,
        variance_threshold=3,
        consecutive_windows=10,
        sigma_threshold=3,
):
    """
    检测并清洗工业数据中的开停车状态数据

    参数:
    df -- 输入的DataFrame，必须包含时间戳列和目标变量列
    target_column -- 要分析的目标列名 (默认: 'TE_02031.PV')
    window_size -- 滑动窗口大小 (默认: 1000)
    variance_threshold -- 方差阈值 (默认: 3)
    consecutive_windows -- 连续窗口数 (默认: 1)
    sigma_threshold -- σ阈值 (默认: 3)
    visualize -- 是否可视化结果 (默认: False)
    save_plot_path -- 可视化结果保存路径 (默认: None)

    返回:
    处理后的DataFrame，包含running_state列(1=正常, 0=开停车)，开停车状态数据被替换为NaN
    """
    # 创建副本避免修改原始DataFrame
    df_processed = df.copy()

    # 初始化 running_state 列（1=正常，0=开停车）
    df_processed['running_state'] = 1

    # 计算均值和标准差（用于辅助检测）
    try:
        print(df_processed[target_column])
        mean_value = df_processed[target_column].mean()
        std_value = df_processed[target_column].std()
        lower_threshold = mean_value - sigma_threshold * std_value
    except Exception as e:
        raise RuntimeError(f"计算均值和标准差错: {target_column, str(e), df_processed.keys()} ")

    # 计算滑动窗口方差（临时列，最后会被移除）
    try:
        df_processed['rolling_var'] = df_processed[target_column].rolling(window=window_size).var()
    except Exception as e:
        raise RuntimeError(f"计算滑动窗口方差错: {str(e)} ")

    # 检测开停车状态
    start_points = []
    end_points = []
    current_state = 1  # 初始状态：正常运行
    start_count = 0
    end_count = 0

    for i in range(window_size, len(df_processed)):
        if df_processed['rolling_var'].iloc[i] > variance_threshold:
            if current_state == 1:
                start_count += 1
                if start_count >= consecutive_windows:
                    start_points.append(i - consecutive_windows * window_size + 1)
                    current_state = 0  # 进入开停车状态
                    end_count = 0
            else:
                end_count = 0  # 重置结束计数器
        else:
            if current_state == 0:
                end_count += 1
                if end_count >= consecutive_windows:
                    end_points.append(i - window_size // 2)
                    current_state = 1  # 返回正常运行
                    start_count = 0
            else:
                start_count = 0  # 重置开始计数器

        # 附加规则：如果值低于 σ下限，直接标记为开停车
        try:
            if df_processed[target_column].iloc[i] < lower_threshold:
                df_processed.loc[df_processed.index[i], 'running_state'] = 0
        except Exception as e:
            raise RuntimeError(f"附加规则错: {str(e)} ")
    # 标记开停车区间
    for start, end in zip(start_points, end_points):
        #TODO 改回=0
        df_processed.loc[df_processed.index[start]:df_processed.index[end], 'running_state'] = 0

    # 开停车状态下，除时间戳列外，所有列替换为 NaN
    # 自动识别时间戳列（假设是第一个datetime列）
    # timestamp_col = df_processed.select_dtypes(include=['datetime']).columns[0]
    # cols_to_nan = [col for col in df_processed.columns if col != timestamp_col and col != 'running_state']
    # df_processed[cols_to_nan] = df_processed[cols_to_nan].where(df_processed['running_state'] == 1, np.nan)

    # 只移除rolling_var临时列，保留running_state列
    df_processed.drop('rolling_var', axis=1, inplace=True, errors='ignore')

    return df_processed


def continuous_data_segment(df, time_col):
    """
    该函数用于将 DataFrame 中的时间序列数据分割成连续的时间段。

    参数:
    - df: DataFrame, 输入的 DataFrame，其中包含时间戳列和其他数据列。
    - time_col: str, 时间戳列的名称。

    返回值:
    - segments: GroupBy 对象, 分割后的连续时间段数据。

    功能:
    该函数首先复制输入的 DataFrame 以避免修改原始数据。

    最终采样间隔（获取数据集中最常见的时间间隔）。
    """
    # 复制输入的 DataFrame
    df_copy = df.copy()
    # 假设时间戳列名为 'Test'
    df_copy[time_col] = pd.to_datetime(df_copy[time_col])
    # 检查时间戳的连续性
    df_copy['time_diff'] = df_copy[time_col].diff().dt.total_seconds()
    # # 找出非连续的时间差
    # non_continuous_mask = df_copy['time_diff'] != df_copy['time_diff'].mode()[0]
    # 采样时间间隔（可选择return）
    df_time_interval = int(df_copy['time_diff'].mode()[0])
    # 删除添加的时间差列
    df_copy.drop(columns=['time_diff'], inplace=True)

    return df_time_interval


def data_process_flow(engine, raw_df, train_table_name, time_col, target_column):
    """
    数据预处理流程，包含异常值处理、缺失值处理、标准化、滤波等步骤

    参数:
    engine - sql数据库连接engine
    raw_df - 原始数据df
    train_table_name - 处理完的训练数据df表名
    test_table_name - 划分出的测试数据df表明

    返回:
    处理后的DataFrame

    功能:
    1. 根据engine参数选择对应的预处理函数
    2. 调用预处理函数处理DataFrame
    3. 返回处理后的DataFrame
    """

    # 0. 首先获取原始数据
    df = raw_df

    print('原始数据读取完成')

    # 1.先进行缺失值处理
    try:
        processed_df = handle_missing_values(df, time_col=time_col, window_size='30T', n_neighbors=5,
                                             debug=False)
    except Exception as e:
        raise RuntimeError(f"缺失值处理失败: {str(e)} ")

    print('缺失值处理完成')

    # 2.再进行异常值处理
    # try:
    #     processed_df = process_outliers(processed_df, window=3, iqr_factor=150, look_back=5, time_col=time_col)
    # except Exception as e:
    #     raise RuntimeError(f"异常值处理失败: {str(e)} ")

    print('异常值处理完成')

    # 3.停车数据标注
    try:
        processed_df = detect_and_clean_shutdown_data(
            processed_df,
            timestamp_col=time_col,
            target_column=target_column,
            window_size=1000,
            variance_threshold=30,
            consecutive_windows=2,
            sigma_threshold=30,
        )
    except Exception as e:
        raise RuntimeError(f"停车数据标注失败: {str(e)} ")
    print('停车数据标注完成')

    # 4.数据存入train_table_name数据库
    # 使用 to_sql 创建表，若表不存在则自动创建

    # processed_df.fillna(0, inplace=True)
    # def is_valid_utf8(s):
    #     try:
    #         if isinstance(s, str):
    #             s.encode('utf-8').decode('utf-8')
    #         return True
    #     except (UnicodeEncodeError, UnicodeDecodeError):
    #         return False
    #
    # def clean_column(series):
    #     return series.map(lambda x: x if is_valid_utf8(x) else np.nan)
    # str_cols = df.select_dtypes(include=['object']).columns
    # for col in str_cols:
    #     df[col] = clean_column(df[col])
    try:
        processed_df.to_sql(
            name=train_table_name,
            con=engine,
            if_exists='replace',  # 如果表不存在则创建，存在则替换
            index=False  # 不保存 DataFrame 索引
        )
    except Exception as e:
        raise RuntimeError(f"训练数据存入数据库失败: {str(e)} ")
    print('训练数据存入数据库完成')
    return processed_df

def analyze_pid_data_quality(test_df, PV_name, MV_name, SV_name):
    # conn = {
    #     'driver': 'psycopg2',
    #     "host": 'seak8sm1.supcon5t.com',
    #     "username": 'postgres',
    #     "password": 'Supcon%401304',
    #     "database": 'spc',
    #     "port": '31230'
    # }
    # url = f"postgresql+{conn['driver']}://{conn['username']}:{conn['password']}@{conn['host']}:{conn['port']}/{conn['database']}"
    # engine = create_engine(url)
    # train_table_name = 'spc_process_control_data'
    # # 从数据库读取数据
    # df = pd.read_sql(f"SELECT * FROM {train_table_name} order by \"Timestamp\" ",
    #                  engine)  # 读取spc_process_data数据库时候需要添加顺序约束
    # test_df = df.reset_index(drop=True)  # （可选）重置索引


    pv = test_df[PV_name]
    mv = test_df[MV_name]
    sv = test_df[SV_name]

    # 0. 有效数据时间戳范围
    # 1. 缺失率
    na_rate = test_df.isna().mean().max()
    if na_rate > 0.33:
        na_rate_check = '缺失值超过总数据量的1/3，需要补充数据集'
    else:
        na_rate_check = '无缺失值，数据集完整'

    # SV是否存在变化的情况
    sv_change_check = f'SV在时刻发生变化'

    # 2. PV 变化量（衡量响应程度）
    pv_range = pv.max() - pv.min()
    pv_range_check = f'PV变化范围为{pv_range}，过程变量响应充足'

    # 3. MV 变化量
    mv_range = mv.max() - mv.min()
    mv_range_check = f'MV控制动作充足且不存在卡限行为'

    # 4. 平滑后的 SNR 估算
    pv_smooth = savgol_filter(pv.ffill().bfill(), window_length=11, polyorder=2)
    noise = pv - pv_smooth
    snr = pv_range / (noise.std() + 1e-6)
    snr_check = '信号清晰'

    # 是否用于推荐（简单规则）
    valid = (
            na_rate < 0.05 and
            pv_range > 1.0 and
            mv_range > 0.5 and
            snr > 5.0
    )
    valid_check = '数据集推荐用于PID参数自整定'

    # --------------- 计算分数 -----------------------#
    # 如果没有指定权重，则默认使用均等权重
    weights = {'na_rate': 0.6, 'pv_range': 0.2, 'mv_range': 0.0, 'snr': 0.2}

    # 标准化每个指标
    # 1. 标准化缺失值比例（na_rate），越低越好
    na_rate_normalized = 1 - na_rate  # 假设 na_rate 在 0 到 1 之间，越小越好

    # 2. PV 和 MV 范围标准化，越大越好，假设范围是大于0的数值，越大表示范围越广
    pv_range_normalized = min(1, pv_range / 100)  # 以100为最大范围来归一化
    mv_range_normalized = min(1, mv_range / 100)  # 假设100为上限

    # 3. SNR标准化，越大越好，通常 SNR 是一个比率，越大代表信噪比越高
    snr_normalized = min(1, snr / 100)  # 假设最大SNR为100

    # 计算加权评分
    score = (na_rate_normalized * weights['na_rate'] +
             pv_range_normalized * weights['pv_range'] +
             mv_range_normalized * weights['mv_range'] +
             snr_normalized * weights['snr']) * 100

    result = {
        'start_time': test_df['Timestamp'].iloc[0],
        'end_time': test_df['Timestamp'].iloc[-1],
        'na_rate': na_rate,
        'na_rate_check': na_rate_check,
        # 'pv_range': pv_range,
        # 'pv_range_check': pv_range_check,
        # 'mv_range': mv_range,
        'mv_range_check': mv_range_check,
        # 'snr': snr,
        # 'snr_check': snr_check,
        'valid_for_tuning': valid,
        'valid_check': valid_check,
        'score': score
    }


    # markdown形式的表格
    def dict_to_markdown_table(data):
        """
        将字典转换为 Markdown 格式的表格字符串。

        :param data: 要转换的字典
        :return: Markdown 格式的表格字符串
        """
        if not data:
            return ""

        # 获取所有键并排序
        keys = sorted(data.keys())

        # 构建表头
        headers = "| " + " | ".join(keys) + " |"
        separators = "| " + " | ".join(["---"] * len(keys)) + " |"

        # 构建表体
        values = "| " + " | ".join(str(data[key]) for key in keys) + " |"

        # 组合表头、分隔符和表体
        markdown_table = f"{headers}\n{separators}\n{values}"

        return markdown_table

    # 创建一个新的字典
    new_result = result.copy()  # 复制原始字典

    # 删除不需要的键
    # for key in ["time_interval", "PV", "MV", "SV"]:
    #     new_result.pop(key, None)  # 使用 pop，避免 KeyError

    markdown_table = dict_to_markdown_table(new_result)
    #print(markdown_table)

    combined_data = {
        'markdown_table': markdown_table
    }

    # 返回 JSON 格式的数据
    # return JSONResponse(content=combined_data)
    return json.dumps(combined_data)

def main(appId, file_info, target_column, MV_name, SV_name):
    try:
        conn = {
            'driver': 'psycopg2',
            "host": 'seak8sm1.supcon5t.com',
            "username": 'postgres',
            "password": 'Supcon%401304',
            "database": 'spc',
            "port": '31230'
        }

        url = f"postgresql+{conn['driver']}://{conn['username']}:{conn['password']}@{conn['host']}:{conn['port']}/{conn['database']}"
        engine = create_engine(url)  # line:685
    except Exception as e:
        raise RuntimeError(f"连接数据库报错: {str(e)} ")
    # try:
    #     raw_df = pd.read_sql(f"SELECT * FROM {raw_table_name}", engine)
    # except Exception as e:
    #     raise RuntimeError(f"读数据报错: {str(e)} ")
    file_data_id = io.StringIO(file_info)
    raw_df = pd.read_csv(file_data_id)
    # for columns_name in raw_df.columns:
    #     if '.' in columns_name:
    #         raw_df[columns_name.split('.')[-1]] = raw_df[columns_name]
    #         raw_df.drop(columns=[columns_name])

    # if target_column != 'PV':
    #     target_column = 'PV'

    train_table_name = 'spc_process_control_data'
    time_col = 'Timestamp'

    base_path = os.path.join('/', 'data', 'spc', f'{appId}', 'classification')

    # 1.进行数据预处理
    processed_df = data_process_flow(engine, raw_df, train_table_name, time_col, target_column)

    # 手动计算采样间隔，单位秒
    sampling_interval = continuous_data_segment(processed_df, time_col)

    # 2.将标准化数据存入指定路径
    try:
        mean_df, std_df = calculate_standardization_stats(processed_df)
        save_standardization_stats(base_path, mean_df, std_df)
    except Exception as e:
        raise RuntimeError(f"标准化数据相关算法错误: {str(e)} ")
    print('success to save dataset! ')
    # 3.数据质量检查
    try:
        tag, score, max_nan = data_quality_check(processed_df, sampling_interval)
    except Exception as e:
        raise RuntimeError(f"数据质量检查错误: {str(e)} ")

    # 构造成字典（JSON格式）
    return_md = analyze_pid_data_quality(raw_df, target_column, MV_name, SV_name)
    # result = {
    #     "tag": tag,
    #     "score": score,
    #     "max_nan": max_nan
    # }

    # 转为 JSON 字符串（如果需要传输或保存）
    # json_result = json.dumps(return_md, indent=2)

    return return_md


async def handle_request_dataProcess(request):
    # 从查询参数中提取参数
    json_data = await request.json()
    config = json_data

    try:
        appId = config.get('appId', '123456')
        file_info = config.get('file_info', 'raw_data')
        target_column = config.get('target_column', 'G_LT_13001.PV')
        MV_name = config.get('MV_name', 'G_LT_13001.PV')
        SV_name = config.get('SV_name', 'G_LT_13001.PV')
        # mv_column = config.get('mv_column', '0123456')
        # sv_column = config.get('sv_column', '0123456')
        # file_data = config.get('file_data', None)


    except Exception as e:
        raise RuntimeError(f"参数解析失败: {str(e)} ")

    # 开始调用main函数
    result = main(appId, file_info, target_column, MV_name, SV_name)  # 对应功能主函数、以及输入的参数（入参）
    return web.Response(text=result)  # 返回请求结果


if __name__ == '__main__':
    with open('D:\\Deep_learn\\TPT2_0\\spc_up_test_10w_10s.csv', 'rb') as file:
        file_data = base64.b64encode(file.read()).decode('utf-8')
    appId = '123456'
    target_column = 'G_LT_13001.PV'
    MV_name = 'G_LT_13001.MV'
    SV_name = 'G_LT_13001.SV'
    main(appId, file_data, target_column, MV_name, SV_name)

