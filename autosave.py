
chunks = {
    "time": 10_000,    # 每块约 10k 个时间点
    "station": 200     # 每块约 200 个 POI
}

# 此处先声明albedo_1到6，以及4个角度
# 声明前，确认H8与H9在ftp上的连续性






# ——— 3. 用 Dask array 申明空变量（全 NaN），但不分配内存
albedo_R = da.full(
    shape=(len(times), len(stations)),
    fill_value=np.nan,
    chunks=(chunks["time"], chunks["station"])
)
# 下面的另一种方法：albedo_NIR = da.full_like(albedo_R, np.nan)
albedo_NIR = da.full(
    shape=(len(times), len(stations)),
    fill_value=np.nan,
    chunks=(chunks["time"], chunks["station"])
)
ds = xr.Dataset(
    data_vars={
        "albedo_R": (("time", "station"), albedo_R,
                     {"units": "unitless", "long_name": "Albedo R band"}),
        "albedo_NIR": (("time", "station"), albedo_NIR,
                       {"units": "unitless", "long_name": "Albedo NIR band"}),
        # … 还可以继续声明 SOZ, SOA, O3, Vapor 等
    },
    # coords={
    #     "time": times,
    #     "station": stations,
    #     "lat": ("station", pois_df["lat"]),
    #     "lon": ("station", pois_df["lon"])
    # }
)

print(ds)

# ——— 5. 按区块填充数据示例
# 假设 loader.read_block 返回一个 NumPy 或 Dask 数组 block_ar，shape 与 (i1-i0, j1-j0) 一致
def fill_block(var_name, i0, i1, j0, j1, block_data):
    ds[var_name][i0:i1, j0:j1] = block_data

# 例如填入 albedo_R 的一个小区块
# block_data = h8_loader.read_albedo_R(times[i0:i1], stations[j0:j1])
# fill_block("albedo_R", i0, i1, j0, j1, block_data)

# ——— 6. 持久化到磁盘（Zarr），此时才真正触发计算并分块写入
zarr_store = os.path.join(Data_path, "h8_dask.zarr")
ds.to_zarr(
    zarr_store,
    mode="w",
    encoding={
        "albedo_R": {"chunks": (chunks["time"], chunks["station"])},
        "albedo_NIR": {"chunks": (chunks["time"], chunks["station"])}
    }
)