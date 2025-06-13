# 20250611 数据链整合，标准化
# prerequisition activate a20250611
#
import numpy as np
import pandas as pd
import xarray as xr
import dask.array as da
import os

Data_path = "D:/H8_data"
POIs_lookuptable_file = os.path.join(Data_path, "station_xy_lookup_table.csv")
POIs_LUTs_df = pd.read_csv(POIs_lookuptable_file, index_col="Station")
stations = POIs_LUTs_df.index

times = pd.date_range("2015-07-07 00:00", "2021-10-31 23:50", freq="10min")


ds = xr.Dataset(coords={
    "time": ("time", times),
    "Station": ("Station", stations),
    "Lat": ("Station", POIs_LUTs_df["Lat"]),
    "Lon": ("Station", POIs_LUTs_df["Lon"]),
    "H8L1_x": ("Station", POIs_LUTs_df["H8L1_x"]),
    "H8L1_y": ("Station", POIs_LUTs_df["H8L1_y"]),
    "L2ARP_x": ("Station", POIs_LUTs_df["L2ARP_x"]),
    "L2ARP_y": ("Station", POIs_LUTs_df["L2ARP_y"]),
    "MOD08_XDim": ("Station", POIs_LUTs_df["MOD08_XDim"]),
    "MOD08_YDim": ("Station", POIs_LUTs_df["MOD08_YDim"]),
    "LUCC_x": ("Station", POIs_LUTs_df["LUCC_x"]),
    "LUCC_y": ("Station", POIs_LUTs_df["LUCC_y"]),
})


save_file_path = os.path.join(Data_path, "LUTs.nc")
ds.to_netcdf(save_file_path)
print(f"LUTs Dataset 已保存在: {save_file_path}")