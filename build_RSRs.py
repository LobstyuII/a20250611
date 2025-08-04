#!/usr/bin/env python3
import numpy as np
import xarray as xr
import pandas as pd
import os

# -------------- 读取 MODIS RSR -------------- #
def read_modis_rsr(path):
    """
    解析 MODIS RSR 文本文件，提取字段并返回 DataFrame。
    期望文件里有 /fields= 行定义列名，/end_header 后是数据块。
    """
    with open(path, 'r') as f:
        lines = f.readlines()

    # 找到 fields 行（不区分大小写）
    field_line = None
    for l in lines:
        if l.strip().lower().startswith("/fields="):
            field_line = l.strip()
            break
    if field_line is None:
        raise ValueError("找不到 /fields= 行，请确认 MODIS 文件格式。")

    # 拿出字段名
    fields = field_line.split('=', 1)[1].split(',')
    fields = [f.strip() for f in fields]

    # 找到数据起始：/end_header 之后
    data_start = None
    for i, l in enumerate(lines):
        if l.strip().lower().startswith("/end_header"):
            data_start = i + 1
            break
    if data_start is None:
        raise ValueError("找不到 /end_header，无法定位数据块。")

    # 读取数据为 DataFrame：用空白分隔
    raw = ''.join(lines[data_start:])
    df = pd.read_csv(
        pd.io.common.StringIO(raw),
        delim_whitespace=True,
        names=fields,
        comment='!',
        na_values=['-999', 'NaN'],
        engine='python'
    )

    # 尝试把波长列统一识别
    wl_col = None
    for candidate in ['wavelength', 'Wavelength', 'Wavelength_nm', 'Wavelength_nm']:
        if candidate in df.columns:
            wl_col = candidate
            break
    if wl_col is None:
        # 兜底：找含 'wave' 的
        for c in df.columns:
            if 'wave' in c.lower():
                wl_col = c
                break
    if wl_col is None:
        raise ValueError("无法识别波长列。现有列: {}".format(df.columns.tolist()))

    # 处理列名预期有 RSR_645 和 RSR_859，如果没有尝试模糊匹配
    def find_best(col_fragment):
        for c in df.columns:
            if col_fragment in c:
                return c
        # 兜底返回 None
        return None

    red_band = find_best('RSR_645') or find_best('645')
    nir_band = find_best('RSR_859') or find_best('859')
    if red_band is None or nir_band is None:
        raise ValueError(f"未找到预期的红/近红外列，现有列: {df.columns.tolist()}")

    # 改名便于后续使用
    df = df.rename(columns={wl_col: 'wavelength', red_band: 'RSR_645', nir_band: 'RSR_859'})

    return df[['wavelength', 'RSR_645', 'RSR_859']]

# -------------- 读取 Himawari RSR -------------- #
def read_himawari_rsr(path):
    """
    解析 Himawari 光谱响应文件（假设按 block 分，含 'Wavelength' 和 'Relative Responsivity' 表格）。
    返回字典： key -> DataFrame with columns wavelength_nm, responsivity
    """
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # 根据 "Model Run:" 划分块
    blocks = content.split("Model Run:")
    channel_dict = {}
    for blk in blocks[1:]:
        lines = blk.splitlines()
        # 尝试找到描述性 key（包含 Flight Model 或 Channel ID）
        key_line = None
        for l in lines[:5]:
            if 'Flight Model' in l or 'CH' in l or 'AHI' in l:
                key_line = l.strip()
                break
        key = key_line if key_line else f"block_{len(channel_dict)+1}"

        # 找表头
        table_start_idx = None
        for i, l in enumerate(lines):
            if 'Wavelength' in l and 'Relative Responsivity' in l:
                table_start_idx = i
                break
        if table_start_idx is None:
            continue  # 找不到数据表就跳过

        # 数据行通常在表头下方 2~3 行之后，尝试找第一行数字
        data_lines = lines[table_start_idx + 1:]
        wl = []
        resp = []
        for l in data_lines:
            if not l.strip():
                continue
            parts = l.strip().split()
            # 期待至少三列：Wavelength[um], something, responsivity
            if len(parts) < 3:
                break
            try:
                wav_um = float(parts[0])
                rr = float(parts[-1])  # 末列是 responsivity
            except ValueError:
                continue
            wl.append(wav_um * 1000.0)  # 转换成 nm
            resp.append(rr)
        if wl:
            df = pd.DataFrame({'wavelength_nm': wl, 'responsivity': resp})
            channel_dict[key] = df

    if not channel_dict:
        raise ValueError("未从 Himawari 文件中解析到任何波段响应块，请检查格式。")

    return channel_dict

# -------------- 重采样函数 -------------- #
def resample_to_grid(wl_source, rsr_source, target_wl):
    """
    把某一响应曲线线性插值到 target_wl 栅格外插 0
    """
    interp = np.interp(target_wl, wl_source, rsr_source, left=0.0, right=0.0)
    return interp

# -------------- 构造并保存 netCDF -------------- #
def build_and_save(modis_df, himawari_channels, output_modis_nc='MODIST_RSRs.nc', output_hima_nc='H8_RSRs.nc'):
    # 定义统一波长格：400 nm 到 900 nm，步长 1 nm
    target_wl = np.arange(400.0, 900.1, 1.0)  # nm

    # 处理 MODIS red 和 NIR
    modis_r = resample_to_grid(
        modis_df['wavelength'].values,
        modis_df['RSR_645'].values,
        target_wl
    )
    modis_nir = resample_to_grid(
        modis_df['wavelength'].values,
        modis_df['RSR_859'].values,
        target_wl
    )
    ds_modis = xr.Dataset(
        {
            'RSR_Red': (('wavelength_nm',), modis_r),
            'RSR_NIR': (('wavelength_nm',), modis_nir),
        },
        coords={'wavelength_nm': target_wl}
    )
    ds_modis.attrs['source'] = 'MODIS Terra (RSR_645 代表 Red, RSR_859 代表 NIR)'
    ds_modis.to_netcdf(output_modis_nc)

    # 自动选 Himawari 对应 Red (~645nm) 和 NIR (~859nm) 的 channel
    centers = {}
    for k, df in himawari_channels.items():
        arr = df[df['responsivity'] > 0]
        if arr.empty:
            continue
        # 加权中心波长
        center = np.sum(arr['wavelength_nm'] * arr['responsivity']) / np.sum(arr['responsivity'])
        centers[k] = center

    if not centers:
        raise ValueError("Himawari 没有任何有效响应用于计算中心波长。")

    # 找最接近的
    def find_best(target):
        return min(centers.items(), key=lambda kv: abs(kv[1] - target))[0]

    red_key = find_best(645.0)
    nir_key = find_best(859.0)

    hima_red = resample_to_grid(
        himawari_channels[red_key]['wavelength_nm'].values,
        himawari_channels[red_key]['responsivity'].values,
        target_wl
    )
    hima_nir = resample_to_grid(
        himawari_channels[nir_key]['wavelength_nm'].values,
        himawari_channels[nir_key]['responsivity'].values,
        target_wl
    )

    ds_hima = xr.Dataset(
        {
            'RSR_Red': (('wavelength_nm',), hima_red),
            'RSR_NIR': (('wavelength_nm',), hima_nir),
        },
        coords={'wavelength_nm': target_wl}
    )
    ds_hima.attrs['source'] = f'Himawari 自动匹配 Red ({red_key}) 和 NIR ({nir_key})'
    ds_hima.to_netcdf(output_hima_nc)

    print(f"保存完成：{output_modis_nc} 和 {output_hima_nc}")
    print(f"MODIS: Red=RSR_645, NIR=RSR_859; Himawari: Red={red_key}, NIR={nir_key}")

# -------------- 主流程 -------------- #
def main():
    # 固定文件名
    himawari_input = r"D:\H8_data\H8_RSRs.txt"
    modis_input = r"D:\H8_data\MODIST_RSRs.txt"
    out_modis = r"D:\H8_data\MODIST_RSRs.nc"
    out_hima = r"D:\H8_data\H8_RSRs.nc"

    # 检查输入文件是否存在
    if not os.path.exists(modis_input):
        raise FileNotFoundError(f"找不到 MODIS 文件: {modis_input}")
    if not os.path.exists(himawari_input):
        raise FileNotFoundError(f"找不到 Himawari 文件: {himawari_input}")

    # 读取
    print("读取 MODIS RSR...")
    modis_df = read_modis_rsr(modis_input)
    print("读取 Himawari RSR...")
    himawari_channels = read_himawari_rsr(himawari_input)

    # 构造 + 保存
    build_and_save(modis_df, himawari_channels, output_modis_nc=out_modis, output_hima_nc=out_hima)


if __name__ == '__main__':
    main()
