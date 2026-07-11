import json
import math

import numpy as np
import pandas as pd
import sys
import os
from urllib.parse import urlencode, urlunparse,quote
import redis
import s3fs
# from scipy.fft import fft, fftfreq
from numpy.fft import fft, fftfreq
from scipy import signal
from statsmodels.tsa.stattools import acf
from tqdm import tqdm
import yaml
import logging
from scipy.signal import find_peaks
import asyncio
from aiohttp import web
from fastapi.responses import JSONResponse
import cache
from sqlalchemy import create_engine
import shlex
import cache
import io
from rediscluster import RedisCluster

# ca = cache.CacheTools('seak8sm2.supcon5t.com', '30380', biz_type="tpt", model="run")
def normalize_series(series):
    """标准化序列（Z-score）"""
    return (series - series.mean()) / series.std() if series.std() > 0 else series


def load_and_preprocess_data(train_df,pv):
    """加载并预处理数据"""
    try:
        df = train_df
        # df = pd.read_csv(train_df)
        print(f"原始CSV总行数: {len(df)}")

        # 数据清洗
        df[pv] = df[pv].interpolate(
            method='akima', limit_direction='both'
        )
        df = df.dropna(subset=[pv])
        print(f"数据清洗后有效点数: {len(df)}")

        return df[pv].values.astype(np.float64)
    except Exception as e:
        print(f"文件读取失败: {str(e)}")
        sys.exit(1)


def periodicity_score(data):
    """周期性综合评分算法"""
    n = len(data)
    # if n < 200:
    #     return -np.inf

    # 频域分析
    detrended = signal.detrend(data)
    freqs = fftfreq(n, 1)[1:n // 2]
    fft_power = np.abs(fft(detrended)[1:n // 2]) ** 2 / n
    spectral_score = np.max(fft_power) / np.mean(np.sort(fft_power)[-5:]) if len(fft_power) >= 5 else 0

    # 时域分析
    max_lag = min(200, n // 2)
    if np.var(data) == 0:
        acf_vals = np.zeros(max_lag + 1)  # 全0自相关
    else:
        acf_vals = acf(data, nlags=max_lag, fft=True, adjusted=True)
    acf_peaks, _ = signal.find_peaks(acf_vals, height=0.2, distance=5)
    temporal_score = acf_vals[acf_peaks[0]] if len(acf_peaks) > 0 else 0

    # 周期一致性验证
    similarity = 0
    if len(acf_peaks) > 1:
        period_candidate = acf_peaks[1] - acf_peaks[0]
        if 5 <= period_candidate <= n // 2:
            segment1 = data[:period_candidate]
            segment2 = data[period_candidate:2 * period_candidate]
            if len(segment1) == len(segment2):
                similarity = np.corrcoef(segment1, segment2)[0, 1]

    return 0.4 * spectral_score + 0.3 * temporal_score + 0.3 * similarity


def dynamic_window_selector(data, num_windows=5, window_size=250):
    """动态窗口选择算法，选出 top N 得分最高的窗口"""
    scores = []
    step = window_size // 2

    for start in range(0, len(data) - window_size, step):
        window = data[start:start + window_size]
        score = periodicity_score(window)
        scores.append((score, start, start + window_size))

    # 按得分排序，选取 top N 窗口
    scores.sort(reverse=True)
    top_windows = scores[:num_windows]
    print(f"找到 {len(top_windows)} 个高质量窗口")
    print(f'top_windows: {top_windows}')
    return [data[s:e] for _, s, e in top_windows], [(s, e) for _, s, e in top_windows]


# def robust_period_detection(data_segments, window_scores=None):
#     """鲁棒周期检测（修正二倍周期问题）"""
#     periods = []
#     weights = []
#
#     for idx, segment in enumerate(data_segments):
#         print(f'segment: {segment}')
#         n = len(segment)
#         if n < 200:
#             continue
#
#
#         # 频域分析（修正基波检测）
#         try:
#             freqs = fftfreq(n, 1)[1:n // 2]
#             fft_power = np.abs(fft(signal.detrend(segment))[1:n // 2] ** 2 / n)
#
#             main_freq_idx = np.argmax(fft_power[4:]) + 4  # 忽略前4个低频分量
#             main_freq = freqs[main_freq_idx]
#             fft_period = int(round(1 / main_freq)) if main_freq > 0 else None
#
#             # 时域分析（强制从第一个峰值计算）
#
#             acf_vals = acf(segment, nlags=min(500, n // 2), fft=True, adjusted=True)
#             height_thresh = max(0.3, np.percentile(acf_vals, 90))
#             print(f'height_thresh: {height_thresh}')
#             acf_peaks, _ = signal.find_peaks(acf_vals, height=height_thresh, distance=2)
#             print(f'acf_peaks: {acf_peaks}')
#         except Exception as e:
#             raise RuntimeError(f"频域分析报错: {str(e)} ")
#         candidates = []
#         if fft_period and 10 <= fft_period <= n // 2:
#             candidates.append(fft_period)
#
#         if len(acf_peaks) >= 1:
#             acf_period = acf_peaks[0]  # 第一个显著峰值
#         else:
#             acf_diff = np.diff(acf_vals)
#             candidate_lag = np.argmin(acf_diff[:20]) + 1  # 前20个点中找最大下降
#             acf_peaks = np.array([candidate_lag])
#             acf_period = acf_peaks[0]
#         # if 10 <= acf_period <= n // 2:
#         print(f'acf_peaks: {acf_peaks}')
#         candidates.append(acf_period)
#
#         # 周期一致性验证（优先选择最小周期）
#         valid_periods = []
#         for p in sorted(candidates):
#             segments = [segment[i:i + p] for i in range(0, n, p) if i + p <= n]
#             if len(segments) < 2:
#                 continue
#             corr_matrix = np.corrcoef(segments, rowvar=False)
#             avg_corr = np.mean(corr_matrix[np.triu_indices(len(corr_matrix), 1)])
#             if avg_corr > 0.5:  # 提高相关性阈值
#                 valid_periods.append(p)
#                 break  # 取第一个满足条件的周期
#         print(f'valid_periods:{valid_periods}')
#         if valid_periods:
#             best_p = min(valid_periods)  # 优先选择最小周期
#             # 检查是否为谐波
#             if best_p > 20 and (best_p // 2) in valid_periods:
#                 best_p = best_p // 2
#             periods.append(best_p)
#             print(f'window_scores:{window_scores}')
#             # weights.append(window_scores[idx] if window_scores else 1.0)
#
#             if window_scores:
#                 weight_data = window_scores[idx]
#                 print(f'weight_data:{weight_data}')
#
#                 if isinstance(weight_data, float) and math.isnan(weight_data):
#                     weight_data = 1.0
#
#             else:
#                 weight_data = 1.0
#             weights.append(weight_data)
#     print(f'weight:{weights}')
#     print(f'periods:{periods}')
#     if not periods:
#         return None, []
#
#     # 加权平均（避免谐波干扰）
#     weighted_avg = np.average(periods, weights=weights)
#     print(f'weighted_avg: {weighted_avg}')
#     return int(round(weighted_avg)), periods

def robust_period_detection(data_segments, window_scores=None):
    """鲁棒周期检测（优化版）"""
    periods = []
    weights = []

    for idx, segment in enumerate(data_segments):
        n = len(segment)
        print(f'segment:{segment}')
        # if n < 200:
        #     continue

        candidates = []
        try:
            # 频域分析（优化）
            fft_power = np.abs(fft(signal.detrend(segment))[1:n // 2] ** 2 / n)
            freqs = fftfreq(n, 1)[1:n // 2]
            min_power = 0.1 * np.max(fft_power)
            valid_mask = (fft_power > min_power) & (freqs > 0)
            if np.any(valid_mask):
                main_freq = freqs[valid_mask][np.argmax(fft_power[valid_mask])]
                fft_period = int(round(1 / main_freq)) if main_freq > 0 else None
                if fft_period and fft_period <= n // 2:
                    candidates.append(fft_period)

            # 时域分析（优化）
            acf_vals = acf(segment, nlags=min(500, n // 2), fft=True, adjusted=True)
            acf_peaks, _ = signal.find_peaks(acf_vals, height=0.3, distance=2)
            print(f'acf_peaks:{acf_peaks}')
            if len(acf_peaks) > 0:
                acf_period = acf_peaks[np.argmax(acf_vals[acf_peaks])]
                if acf_period <= n // 2:
                    candidates.append(acf_period)

        except Exception as e:
            print(f"警告: 段 {idx} 分析失败 - {str(e)}")
            continue

        # 周期验证（优化）
        valid_periods = []
        print(f'candidates:{candidates}')
        for p in sorted(set(candidates)):  # 去重
            if p > n // 2:
                continue
            segments = [segment[i:i + p] for i in range(0, n, p) if i + p <= n]
            print(f'segments: {segments}')
            # if len(segments) < 2:
            #     continue
            corr_matrix = np.corrcoef(segments, rowvar=False)
            print(f'corr_matrix:{corr_matrix}')
            avg_corr = np.mean(corr_matrix[np.triu_indices(len(corr_matrix), 1)])
            # if avg_corr > 0.3:  # 降低阈值
            valid_periods.append(p)
        print(f'valid_periods:{valid_periods}')
        # 谐波修正
        if valid_periods:
            best_p = valid_periods[0]
            for p in valid_periods[1:]:
                if any(abs(p / best_p - k) < 0.1 for k in [2, 3, 4]):
                    best_p = min(best_p, p)
            periods.append(best_p)
            weights.append(window_scores[idx] if window_scores else 1.0)
    print(f'periods:{periods}')
    if not periods:
        return None, []

    # 加权平均（显式归一化权重）
    weights = np.array(weights) / np.sum(weights) if window_scores else None
    print(f'weights:{weights}')
    weighted_avg = np.average(periods, weights=weights)
    print(f'weighted_avg: {weighted_avg}')
    if np.isnan(weighted_avg):
        weighted_avg = 0
    print(f'weighted_avg: {weighted_avg}')
    print(round(weighted_avg))
    return int(round(weighted_avg)), periods


def to_native(obj):
    """
    递归将对象中的 numpy 类型和非标量类型转换为 YAML 可接受的类型。
    """
    if isinstance(obj, dict):
        return {to_native(k): to_native(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_native(i) for i in obj]
    elif isinstance(obj, tuple):
        return tuple(to_native(i) for i in obj)
    elif isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        return float(obj)
    elif isinstance(obj, (np.bool_)):
        return bool(obj)
    elif isinstance(obj, (np.ndarray,)):
        return [to_native(i) for i in obj.tolist()]
    else:
        return obj


def add_yaml(local_path, data_dir):
    """将分析结果写入本地YAML文件（使用ruamel.yaml格式化）"""
    try:
        # 递归转换为 YAML 支持的类型
        cleaned_data = to_native(data_dir)
        # 读取现有数据
        # if os.path.exists(local_path):
        #     with open(local_path, 'r', encoding='utf-8') as file:
        #         existing_data = yaml.safe_load(file) or {}
        # else:
        #     existing_data = {}
        #     with open(local_path, 'w', encoding='utf-8') as file:
        #         yaml.dump(existing_data, file)

        fs = s3fs.S3FileSystem()
        if fs.exists(local_path):
            with fs.open(local_path, 'r') as file:
                existing_data = yaml.safe_load(file) or {}
        else:
            existing_data = {}
            fs.mkdir(local_path)

        write_yaml = {**existing_data, **cleaned_data}
        # with open(local_path, 'w', encoding='utf-8') as file:
        #     yaml.dump(write_yaml, file)
        with fs.open(local_path, 'w') as file:
            yaml.dump(write_yaml, file, default_flow_style=False)
        print(f"YAML已保存至 {local_path}")
    except Exception as e:
        print(f"YAML写入异常：{str(e)}")


def analyze_periodicity(data, local_path,time_interval):
    """周期性分析主函数"""
    data_segments, windows = dynamic_window_selector(data)
    print(f'data_segments: {data_segments}')
    if not data_segments:
        print("未找到有效窗口，无法分析周期")
        result = {
            "period": {
                "points": 0,
                "seconds": 0,
                "has_period": False,
                "window": {"start": 0, "end": 0},
                "all_periods": []
            }
        }
        add_yaml(local_path, result)
        return

    # 获取窗口对应的评分作为权重
    window_scores = [periodicity_score(seg) for seg in data_segments]
    try:
        period, all_periods = robust_period_detection(data_segments, window_scores)
    except Exception as e:
        raise RuntimeError(f"计算period报错: {str(e)} ")

    # if period < 100:
    #     period = period * 5
    #     all_periods = [x * 5 for x in all_periods]
    # 构建分析结果
    result = {
        "period": {
            "points": period if period else 0,
            "seconds": (period * time_interval) if period else 0,
            "has_period": bool(period),
            "window": {"start": windows[0][0], "end": windows[0][1]},
            "all_periods": all_periods
        }
    }
    try:
        add_yaml(local_path, result)
    except Exception as e:
        raise RuntimeError(f"写入yaml报错: {str(e)} ")
    cycle = period
    return cycle


def dict_to_markdown_table(data):

    if not data:
        return ""

    max_length = max(len(value) if isinstance(value, list) else 1 for value in data.values())
    expanded_data = {}
    for key, value in data.items():
        if isinstance(value, list):
            expanded_value = value + [''] * (max_length - len(value))
        else:
            expanded_value = [value] * max_length
        expanded_data[key] = expanded_value

    keys = list(expanded_data.keys())
    column_widths = {key: max(len(str(key)), max(len(str(item)) for item in expanded_data[key])) for key in keys}

    headers = "| " + " | ".join(f"{key:<{column_widths[key]}}" for key in keys) + " |"
    separators = "| " + " | ".join(["-" * column_widths[key] for key in keys]) + " |"

    table_rows = []
    for i in range(max_length):
        row = "| " + " | ".join(f"{str(expanded_data[key][i]):<{column_widths[key]}}" for key in keys) + " |"
        table_rows.append(row)

    markdown_table = f"{headers}\n{separators}\n" + "\n".join(table_rows)

    return markdown_table

def continuous_data_segment(df,time_col):
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


class Config:
    # fixed
    TENANT_ID = "0"  # 租户
    # REDIS_HOST = "seak8sm1.supcon5t.com"  #dev redis地址
    # REDIS_PORT = 26379  #dev redis端口
    REDIS_HOST = "redis-master.devops"  # test redis地址
    REDIS_PORT = 6379  #test redis端口
    REDIS_DB = 2  # redis数据库
    RUNTIME_URL = "http://10.30.73.42:31668/stream_train_logs/"  # 运行时sse调用接口
    TIME_OUT = 3000  # 算法执行超时时间

    # changed
    SPC_PID_IDENTIFICATION_TOPIC = "single_python_train_spc_pid_identification"  # 发送预测算法执行topic
    SPC_PID_IDENTIFICATION_TOPIC_RES = "single_python_train_spc_pid_identification_res"  # 预测算法响应topic
    SPC_PID_IDENTIFICATION_ALG_NAME = "spc_pid_identification_analysis_train"  # 与算法文件名对应
    SPC_PID_IDENTIFICATION_ALG_FULL_NAME = "spc_pid_identification_analysis_train.py"  # 与算法文件名对应
    TASK_NAME = "SPC:PID:IDENTIFICATION"

def main(config):
    ca = cache.CacheTools(redis_host='localhost', redis_port='6379', model="run")
    print('获取ca')
    # # 获取对应集群的redis地址
    # redis_host = ca.configs.get("redis", "host")
    # redis_port = ca.configs.get("redis", "port")
    # redis_db = ca.configs.get("redis", "db")
    # rs_result = redis.Redis(host=redis_host, port=redis_port, db=redis_db)

    # 获取redis集群的模式，字符串'1' 代表集群模式，其他代表单机模式
    print('开始获取redis')
    redis_cluster_model = ca.configs.get("biz", "redis_cluster")
    redis_host = ca.configs.get("redis", "host")
    redis_port = ca.configs.get("redis", "port")
    redis_db = ca.configs.get("redis", "db")
    redis_password = ca.configs.get("redis", "password")

    if redis_cluster_model == '1':
        startup_nodes = [{"host": redis_host, "port": redis_port}]
        rs_result = RedisCluster(startup_nodes=startup_nodes, password=redis_password, decode_responses=True)

    else:
        pool = redis.ConnectionPool(host=redis_host, port=redis_port, db=redis_db, password=redis_password,
                                    decode_responses=True)
        rs_result = redis.Redis(connection_pool=pool)
    is_test = False
    print('已获取redis')
    # appId = config.get('appId', '123456')
    time_interval = config.get('time_interval', 10)
    mv = config.get('mv', None)
    pv = config.get('pv', None)
    sv = config.get('sv', None)
    mv_pv_pos_neg = config.get('mv_pv_correlation', None)
    clientId = config['clientId']
    appId = clientId
    # conn = {
    #     'driver': 'psycopg2',
    #     "host": 'seak8sm1.supcon5t.com',
    #     "username": 'postgres',
    #     "password": 'Supcon%401304',
    #     "database": 'spc',
    #     "port": '31230'
    # }
    print("获取时序数据库连接信息")
    timescaladb_user = ca.configs.get("biz", "timescaladb_user")
    timescaladb_password = ca.configs.get("biz", "timescaladb_password")
    timescaladb_host = ca.configs.get("biz", "timescaladb_host")
    timescaladb_port = ca.configs.get("biz", "timescaladb_port")
    
    conn = {
        'driver': 'psycopg2',
        "host": timescaladb_host,
        "username": timescaladb_user,
        "password": quote(timescaladb_password),  # Supcon@1304
        "database": 'spc',
        "port": timescaladb_port
    }
    print("时序数据库连接信息获取成功")
    url = f"postgresql+{conn['driver']}://{conn['username']}:{conn['password']}@{conn['host']}:{conn['port']}/{conn['database']}"
    engine = create_engine(url)

    table_name = f'{appId}_spc_process_control_data'

    train_df = pd.read_sql(f'SELECT * FROM "{table_name}"', engine)


    local_path = os.path.join('0.data', 'spc', f'{appId}', 'statistic', 'pid_statistic_param.yaml')

    # 计算周期
    time_interval = continuous_data_segment(train_df,'Timestamp')

    data = load_and_preprocess_data(train_df,pv)
    cycle = analyze_periodicity(data, local_path,time_interval)
    print(f'cycle: {cycle}')

    cycle = cycle if cycle is not None else 0
    def find_first_change_index(series):
        if len(series) == 0:
            return 0

        first_value = series.iloc[0]
        print(f'first_value: {first_value}')
        for i, value in enumerate(series):
            if not np.isclose(value, first_value):
                return i
        return len(series)  # 如果全部相同
    print('-----------------------------------------------------------------------------')
    print(f'type: {type(train_df)}')
    print(f"df[SV]: {train_df[sv]}")
    change_idx = find_first_change_index(train_df[sv])
    if change_idx == len(train_df):
        subset_df = train_df
    else:
        subset_df = train_df.iloc[:change_idx]
    if not subset_df.empty:
        abs_diff = (subset_df[sv] - subset_df[pv]).abs().mean()
        result = abs_diff / (subset_df[sv].mean())
    else:
        result = np.nan  # 如果没有数据，返回NaN
    print("结果:", result)
    if result >= 0.01:
        Volatility_assessment = '波动大'
    else:
        Volatility_assessment = '波动小'

    SV = train_df[sv].iloc[-1]
    PV_trajectory = train_df[pv]
    sampling_time = time_interval
    for j in range(1, len(PV_trajectory)):
        if SV < PV_trajectory[0]:
            if PV_trajectory[j] <= PV_trajectory[0] + (SV - PV_trajectory[0]) * 0.9 and \
                    PV_trajectory[j - 1] >= SV:
                cross_index = j
                response_time = cross_index * sampling_time  # 第一次达到或超过 SV 的时间
                break
            else:
                response_time = (len(PV_trajectory) - 1) * sampling_time
        else:
            # if PV_trajectory[j] >= last_SV + (SV - last_SV) * 0.9 and PV_trajectory[j - 1] <= SV:
            if PV_trajectory[j] >= PV_trajectory[0] + (SV - PV_trajectory[0]) * 0.9 and \
                    PV_trajectory[j - 1] <= SV:
                cross_index = j
                response_time = cross_index * sampling_time  # 第一次达到或超过 SV 的时间
                break
            else:
                response_time = (len(PV_trajectory) - 1) * sampling_time
    print(f'response_time: {response_time}')
    if response_time > 300:
        response_status = '目标跟踪速度缓慢，过程变量响应速度较慢'
    else:
        response_status = '目标跟踪速度迅速，过程变量响应速度迅速'

    result = train_df[pv].std()
    dictionary = {'周期': f'{cycle*sampling_time}s',
                  '波动标准差': "{:.2f}".format(result),
                  #'Volatility_assessment':Volatility_assessment,
                  '响应状态': response_status}
    markdown_table = dict_to_markdown_table(dictionary)
    combined_data = {'markdown_output': markdown_table,
                     'Cycle': cycle * sampling_time,
                     'Range': result,
                     'Volatility_assessment': Volatility_assessment,
                     'Response_status': response_status
                     }

    rs_result.set(
        name=f"{Config.SPC_PID_IDENTIFICATION_TOPIC}_" + clientId,  # 键名
        value=json.dumps(combined_data),  # 值（JSON 字符串）
        ex=3600  # 可选：设置过期时间（秒）
    )
    # return JSONResponse(content=combined_data)


# async def handle_request(request):
#     params = {
#         'id':'123456',
#         'appId':'123456',
#         'pv_target': 'PV',
#         'mv_control': 'MV',
#         'time_interval':10,
#         'mv_pv_correlation': 1
#     }
#     params = json.dumps(params)
#
#
#     result = main(params)
#     return web.Response(text=result)  # 返回请求结果
#     # return web.Response(json=result) # 也可以写成这样，具体看需要返回的出参类型
#
#
#
#
# if __name__ == '__main__':
#     # _cycle_main()
#     main()
#     # asyncio.run(start_service())