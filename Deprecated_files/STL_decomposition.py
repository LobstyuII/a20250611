import os
import sys
import logging
import numpy as np
import xarray as xr
import pandas as pd
from scipy import interpolate
from statsmodels.tsa.seasonal import MSTL
from pathlib import Path


# 自定义日志过滤器 - 允许非warning级别的日志通过
class NotWarningFilter(logging.Filter):
    def filter(self, record):
        return record.levelno != logging.WARNING


# 设置日志配置
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 文件日志处理器
file_handler = logging.FileHandler('h8l1_decomposition.log')
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# 终端日志处理器
console_handler = logging.StreamHandler(sys.stdout)
console_formatter = logging.Formatter('%(asctime)s - %(message)s')
console_handler.setFormatter(console_formatter)
console_handler.addFilter(NotWarningFilter())  # 过滤掉warning级别的日志
logger.addHandler(console_handler)


def process_station_data(ds, station, var_name, time_range):
    """处理单个站点的数据：平滑、插值、STL分解（适配10分钟频率数据）"""
    # 选择特定站点和时间范围的数据
    station_ds = ds.sel(Station=station, time=slice(*time_range))
    var_data = station_ds[var_name]

    # 物理范围有效性检查：Albedo值应在[0,1]之间
    var_data = var_data.where((var_data >= 0) & (var_data <= 1))
    logger.info(f"站点 {station}: 过滤后有效数据比例 {np.sum(~np.isnan(var_data))}/{len(var_data)}")

    # 检查数据长度
    data_length = len(var_data.time)
    logger.info(f"处理站点 {station}: 数据长度 = {data_length} 个时间点 (10分钟频率)")

    # 数据预处理 - 使用PCHIP插值（保持范围保守性）
    if np.isnan(var_data).any():
        logger.info(f"站点 {station}: 检测到缺失值，执行PCHIP插值")
        # 转换为数值时间戳用于插值
        time_numeric = var_data.time.astype(np.int64)
        valid_mask = ~np.isnan(var_data)

        # 使用PCHIP插值（分段三次Hermite插值）
        interp_func = interpolate.PchipInterpolator(
            time_numeric[valid_mask],
            var_data[valid_mask],
            extrapolate=False  # 禁止外推
        )
        # 仅对内部缺失值插值（不处理边缘外推）
        interpolated = interp_func(time_numeric[~valid_mask])
        var_data[~valid_mask] = interpolated

        # 检查插值结果是否超出物理范围
        out_of_bounds = np.sum((interpolated < 0) | (interpolated > 1))
        if out_of_bounds > 0:
            logger.warning(f"站点 {station}: 插值后 {out_of_bounds} 个值超出物理范围")
            # 强制约束在[0,1]范围内
            var_data = var_data.clip(0, 1)

    # 数据平滑 (使用滚动平均)
    window_size = min(5, data_length)  # 自适应窗口大小
    if window_size > 1:
        logger.info(f"站点 {station}: 应用窗口大小为 {window_size} 的平滑处理")
        var_data = var_data.rolling(time=window_size, center=True, min_periods=1).mean()

    # 转换为pandas Series用于STL分解
    time_index = pd.to_datetime(var_data.time.values)
    ts = pd.Series(var_data.values, index=time_index)

    # 确定周期参数 (适配10分钟频率)
    periods = []

    # 10分钟频率的周期定义
    MINUTES_PER_DAY = 144  # 24小时 * 6点/小时
    DAYS_PER_YEAR = 365
    yearly_period = DAYS_PER_YEAR * MINUTES_PER_DAY

    # 修复周期检测逻辑
    min_days_for_diurnal = 2  # 只需2天数据就能检测日周期
    min_days_for_yearly = 730  # 2年数据

    # 计算实际数据天数
    total_days = (time_index[-1] - time_index[0]).days + 1

    # 日周期检测
    enable_diurnal = False
    if total_days >= min_days_for_diurnal:
        periods.append(MINUTES_PER_DAY)
        enable_diurnal = True
        logger.info(f"站点 {station}: 启用日周期分解 (周期={MINUTES_PER_DAY})")
    else:
        logger.info(f"站点 {station}: 数据不足{min_days_for_diurnal}天，禁用日周期分解")

    # 年周期检测
    enable_yearly = False
    if total_days >= min_days_for_yearly:
        periods.append(yearly_period)
        enable_yearly = True
        logger.info(f"站点 {station}: 启用年周期分解 (周期={yearly_period})")
    else:
        logger.info(f"站点 {station}: 数据不足{min_days_for_yearly}天，禁用年周期分解")

    # 执行MSTL分解
    if periods:
        try:
            result = MSTL(ts, periods=periods).fit()
        except Exception as e:
            logger.error(f"站点 {station}: MSTL分解失败: {str(e)}")
            raise

        # 初始化分量
        components = {
            'trend': result.trend,
            'resid': result.resid,
            'yearly': pd.Series(0, index=time_index),
            'diurnal': pd.Series(0, index=time_index)
        }

        # 检查分量类型
        if isinstance(result.seasonal, pd.DataFrame):
            # 多个分量情况
            seasonal_df = result.seasonal
            comp_names = seasonal_df.columns.tolist()
            logger.info(f"站点 {station}: 可用的分量名称: {comp_names}")

            # 提取分量
            for comp_name in comp_names:
                if 'seasonal' in comp_name:
                    # 根据名称中的周期值分配分量
                    if str(MINUTES_PER_DAY) in comp_name and enable_diurnal:
                        components['diurnal'] = seasonal_df[comp_name]
                        logger.info(f"站点 {station}: 分配为日周期分量 '{comp_name}'")
                    elif str(yearly_period) in comp_name and enable_yearly:
                        components['yearly'] = seasonal_df[comp_name]
                        logger.info(f"站点 {station}: 分配为年周期分量 '{comp_name}'")
        else:
            # 单一分量情况
            seasonal_series = result.seasonal
            comp_name = seasonal_series.name
            logger.info(f"站点 {station}: 单一分量模式, 分量名称: '{comp_name}'")

            # 根据启用的周期分配分量
            if enable_diurnal and not enable_yearly:
                # 只有日周期启用
                components['diurnal'] = seasonal_series
                logger.info(f"站点 {station}: 分配为日周期分量")
            elif enable_yearly and not enable_diurnal:
                # 只有年周期启用
                components['yearly'] = seasonal_series
                logger.info(f"站点 {station}: 分配为年周期分量")
            elif enable_diurnal and enable_yearly:
                # 两个周期都启用 - 需要更复杂的处理
                logger.warning(f"站点 {station}: 无法确定单一分量类型，使用零值替代")
            else:
                logger.warning(f"站点 {station}: 未启用任何周期，使用零值替代")

        # 调试日志：检查分量值范围
        logger.info(
            f"站点 {station} - 日周期分量范围: [{components['diurnal'].min():.4f}, {components['diurnal'].max():.4f}]")
        logger.info(
            f"站点 {station} - 年周期分量范围: [{components['yearly'].min():.4f}, {components['yearly'].max():.4f}]")

        return {
            'trend': components['trend'].values,
            'yearly': components['yearly'].values,
            'diurnal': components['diurnal'].values,
            'resid': components['resid'].values
        }
    else:
        # 如果不满足任何周期条件，使用简单分解
        logger.warning(f"站点 {station}: 数据不足，使用简单趋势分解")
        trend = ts.rolling(window=min(24, len(ts)), min_periods=1, center=True).mean()
        resid = ts - trend
        return {
            'trend': trend.values,
            'yearly': np.zeros_like(trend.values),
            'diurnal': np.zeros_like(trend.values),
            'resid': resid.values
        }


def main():
    # 输入参数
    NC_PATH = "D:\\H8_data\\H8L1\\2015\\08\\H8_monthly_201508.nc"
    STATIONS = ["1001A", "1002A", "1003A"]
    TIME_RANGE = ("2015-08-01", "2015-08-30")
    VAR_NAME = "Albedo_04"

    logger.info(f"开始处理: {NC_PATH}")
    logger.info(f"目标站点: {STATIONS}")
    logger.info(f"时间范围: {TIME_RANGE}")
    logger.info(f"处理变量: {VAR_NAME}")

    try:
        # 打开NetCDF文件
        with xr.open_dataset(NC_PATH) as ds:
            # 创建输出目录
            output_dir = Path(f"D:/H8_Data/Decomposition/{VAR_NAME}")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"decomposed_{Path(NC_PATH).name}"

            # 创建新的数据集结构
            time_slice = ds.sel(time=slice(*TIME_RANGE)).time
            new_ds = xr.Dataset(
                coords={
                    'Station': STATIONS,
                    'time': time_slice
                }
            )

            # 为每个分量创建数据数组
            for suffix in ['trend', 'yearly', 'diurnal', 'err']:
                var_name_full = f"{VAR_NAME}_{suffix}"
                data = np.empty((len(STATIONS), len(time_slice)))
                data[:] = np.nan
                new_ds[var_name_full] = xr.DataArray(
                    data=data,
                    dims=('Station', 'time'),
                    coords={'Station': STATIONS, 'time': time_slice},
                    attrs={'description': f'STL decomposition: {suffix} component'}
                )

            # 逐个站点处理
            for i, station in enumerate(STATIONS):
                logger.info(f"处理站点: {station} ({i + 1}/{len(STATIONS)})")

                # 执行STL分解
                results = process_station_data(ds, station, VAR_NAME, TIME_RANGE)

                # 将结果填充到新数据集
                new_ds[f"{VAR_NAME}_trend"][i, :] = results['trend']
                new_ds[f"{VAR_NAME}_yearly"][i, :] = results['yearly']
                new_ds[f"{VAR_NAME}_diurnal"][i, :] = results['diurnal']
                new_ds[f"{VAR_NAME}_err"][i, :] = results['resid']

            # 保存结果到新文件
            encoding = {var: {'zlib': True, 'complevel': 5} for var in new_ds.data_vars}
            new_ds.to_netcdf(output_path, encoding=encoding)
            logger.info(f"处理完成! 结果保存至: {output_path}")

    except Exception as e:
        logger.exception(f"处理过程中发生错误: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()