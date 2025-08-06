import numpy as np
import xarray as xr
import os
import matplotlib.pyplot as plt

# 1. Define file paths and land cover types
modis_rsr_path = r'D:\H8_data\MODIST_RSRs.nc'
h8_rsr_path = r'D:\H8_data\H8_RSRs.nc'
usgs_dir = r'D:\H8_data\USGS'

landcover_types = {
    'Evergreen': [1, 2, 5],
    'Deciduous': [3, 4],
    'Grass': [6, 7, 8, 9, 10],
    'Cropland': [12, 14],
    'Urban': [13],
    'Barren': [16]
}

# 2. Load RSR data
modis_rsr = xr.open_dataset(modis_rsr_path)
h8_rsr = xr.open_dataset(h8_rsr_path)

# Check wavelength consistency
assert np.allclose(modis_rsr.wavelength_nm.values, h8_rsr.wavelength_nm.values), "Wavelength mismatch!"
wavelengths = modis_rsr.wavelength_nm.values

# 3. Initialize coefficient storage for all three BRDF parameters
coefficients = {
    'Red': {},
    'NIR': {}
}

# 4. Process each land cover type
for lc_type in landcover_types:
    # Load hyperspectral data
    ds = xr.open_dataset(os.path.join(usgs_dir, f"{lc_type}.nc"))

    # Get reflectance data (501 wavelengths)
    reflectance = ds.reflectance.values.squeeze()

    # Handle NaN values - replace with 0
    reflectance = np.nan_to_num(reflectance, nan=0.0)

    # 5. Calculate band reflectance
    # MODIS bands
    modis_red = np.sum(reflectance * modis_rsr.RSR_Red.values) / np.sum(modis_rsr.RSR_Red.values)
    modis_nir = np.sum(reflectance * modis_rsr.RSR_NIR.values) / np.sum(modis_rsr.RSR_NIR.values)

    # Himawari bands
    h8_red = np.sum(reflectance * h8_rsr.RSR_Red.values) / np.sum(h8_rsr.RSR_Red.values)
    h8_nir = np.sum(reflectance * h8_rsr.RSR_NIR.values) / np.sum(h8_rsr.RSR_NIR.values)

    # 6. Calculate conversion coefficients (direct ratio)
    # Add protection against division by zero
    a_red = h8_red / modis_red if modis_red > 1e-6 else 1.0
    a_nir = h8_nir / modis_nir if modis_nir > 1e-6 else 1.0

    # 7. Store coefficients (same for all BRDF parameters)
    coefficients['Red'][lc_type] = a_red
    coefficients['NIR'][lc_type] = a_nir

    print(f"\n{lc_type} conversion coefficients:")
    print(f"Red band: a = {a_red:.4f} (MODIS: {modis_red:.4f}, H8: {h8_red:.4f})")
    print(f"NIR band: a = {a_nir:.4f} (MODIS: {modis_nir:.4f}, H8: {h8_nir:.4f})")

    # 8. Visualize spectrum and SRF (English only)
    plt.figure(figsize=(12, 8))

    # Spectral curve
    plt.subplot(2, 1, 1)
    plt.plot(wavelengths, reflectance, 'k-', label='Hyperspectral Reflectance')
    plt.title(f'{lc_type} Spectral Response')
    plt.xlabel('Wavelength (nm)')
    plt.ylabel('Reflectance')
    plt.grid(True)
    plt.legend()

    # SRF curves
    plt.subplot(2, 1, 2)
    plt.plot(wavelengths, modis_rsr.RSR_Red.values, 'r-', label='MODIS Red SRF')
    plt.plot(wavelengths, modis_rsr.RSR_NIR.values, 'b-', label='MODIS NIR SRF')
    plt.plot(wavelengths, h8_rsr.RSR_Red.values, 'r--', label='Himawari Red SRF')
    plt.plot(wavelengths, h8_rsr.RSR_NIR.values, 'b--', label='Himawari NIR SRF')
    plt.title('Sensor Response Functions')
    plt.xlabel('Wavelength (nm)')
    plt.ylabel('Response')
    plt.legend()
    plt.grid(True)

    plt.tight_layout()
    plt.savefig(os.path.join(usgs_dir, f"{lc_type}_spectrum_and_srf.png"))
    plt.close()

# 9. Save coefficients to file
output_path = os.path.join(usgs_dir, "BRDF_conversion_coefficients.nc")
coef_ds = xr.Dataset(
    {
        'red_coef': xr.DataArray(
            data=[coefficients['Red'][lc] for lc in landcover_types],
            dims=['landcover'],
            coords={'landcover': list(landcover_types.keys())}
        ),
        'nir_coef': xr.DataArray(
            data=[coefficients['NIR'][lc] for lc in landcover_types],
            dims=['landcover'],
            coords={'landcover': list(landcover_types.keys())}
        ),
    },
    attrs={
        'title': 'BRDF Conversion Coefficients',
        'description': 'Scaling coefficients for converting MODIS BRDF parameters to Himawari',
        'parameters': 'Applies to f_iso, f_vol, and f_geo parameters',
        'method': 'Direct calculation based on typical spectra and sensor SRFs',
        'created': str(np.datetime64('now'))
    }
)
coef_ds.to_netcdf(output_path)
print(f"\nConversion coefficients saved to: {output_path}")


# 10. Reconstruct Himawari BRDF parameters function
def reconstruct_brdf(lc_type, modis_red_brdf, modis_nir_brdf, coefficients):
    """
    Reconstruct Himawari BRDF parameters (f_iso, f_vol, f_geo) for both bands

    Parameters:
    lc_type: Land cover type (e.g., 'Deciduous')
    modis_red_brdf: Tuple of MODIS red band BRDF parameters (f_iso_red, f_vol_red, f_geo_red)
    modis_nir_brdf: Tuple of MODIS NIR band BRDF parameters (f_iso_nir, f_vol_nir, f_geo_nir)
    coefficients: Precomputed conversion coefficients

    Returns:
    (h8_red_brdf, h8_nir_brdf): Himawari BRDF parameters for red and NIR bands
    """
    a_red = coefficients['Red'][lc_type]
    a_nir = coefficients['NIR'][lc_type]

    # Unpack MODIS parameters for red band
    modis_red_iso, modis_red_vol, modis_red_geo = modis_red_brdf
    # Unpack MODIS parameters for NIR band
    modis_nir_iso, modis_nir_vol, modis_nir_geo = modis_nir_brdf

    # Apply conversion to red band parameters
    h8_red_iso = a_red * modis_red_iso
    h8_red_vol = a_red * modis_red_vol
    h8_red_geo = a_red * modis_red_geo

    # Apply conversion to NIR band parameters
    h8_nir_iso = a_nir * modis_nir_iso
    h8_nir_vol = a_nir * modis_nir_vol
    h8_nir_geo = a_nir * modis_nir_geo

    # Return tuples of converted parameters
    red_brdf = (h8_red_iso, h8_red_vol, h8_red_geo)
    nir_brdf = (h8_nir_iso, h8_nir_vol, h8_nir_geo)

    return red_brdf, nir_brdf


# 11. Full image processing function
def apply_brdf_conversion(lc_map, modis_red_brdf, modis_nir_brdf, coefficients):
    """
    Apply BRDF conversion to entire image for all parameters

    Parameters:
    lc_map: 2D land cover classification map (same size as BRDF arrays)
    modis_red_brdf: Tuple of MODIS red band BRDF maps (f_iso_red, f_vol_red, f_geo_red)
    modis_nir_brdf: Tuple of MODIS NIR band BRDF maps (f_iso_nir, f_vol_nir, f_geo_nir)
    coefficients: Precomputed conversion coefficients

    Returns:
    (h8_red_brdf, h8_nir_brdf): Himawari BRDF parameters maps for red and NIR bands
    """
    # Unpack MODIS BRDF maps
    modis_red_iso, modis_red_vol, modis_red_geo = modis_red_brdf
    modis_nir_iso, modis_nir_vol, modis_nir_geo = modis_nir_brdf

    # Initialize result arrays for red band
    h8_red_iso = np.zeros_like(modis_red_iso)
    h8_red_vol = np.zeros_like(modis_red_vol)
    h8_red_geo = np.zeros_like(modis_red_geo)

    # Initialize result arrays for NIR band
    h8_nir_iso = np.zeros_like(modis_nir_iso)
    h8_nir_vol = np.zeros_like(modis_nir_vol)
    h8_nir_geo = np.zeros_like(modis_nir_geo)

    # Apply conversion for each land cover type
    for lc_type in landcover_types:
        # Create mask for current land cover type
        mask = np.isin(lc_map, landcover_types[lc_type])

        # Get conversion coefficients
        a_red = coefficients['Red'][lc_type]
        a_nir = coefficients['NIR'][lc_type]

        # Apply conversion to red band parameters
        h8_red_iso[mask] = a_red * modis_red_iso[mask]
        h8_red_vol[mask] = a_red * modis_red_vol[mask]
        h8_red_geo[mask] = a_red * modis_red_geo[mask]

        # Apply conversion to NIR band parameters
        h8_nir_iso[mask] = a_nir * modis_nir_iso[mask]
        h8_nir_vol[mask] = a_nir * modis_nir_vol[mask]
        h8_nir_geo[mask] = a_nir * modis_nir_geo[mask]

    # Return tuples of converted maps
    red_brdf = (h8_red_iso, h8_red_vol, h8_red_geo)
    nir_brdf = (h8_nir_iso, h8_nir_vol, h8_nir_geo)

    return red_brdf, nir_brdf


# Example usage
if __name__ == "__main__":
    # Sample MODIS BRDF values for both bands
    modis_red_brdf = (0.15, 0.08, 0.05)  # (f_iso, f_vol, f_geo) for red band
    modis_nir_brdf = (0.25, 0.12, 0.07)  # (f_iso, f_vol, f_geo) for NIR band
    lc_type = "Deciduous"

    # Reconstruct Himawari BRDF parameters
    h8_red_brdf, h8_nir_brdf = reconstruct_brdf(
        lc_type,
        modis_red_brdf,
        modis_nir_brdf,
        coefficients
    )

    print(f"\nReconstruction example ({lc_type}):")
    print("Input MODIS Red BRDF: f_iso={:.4f}, f_vol={:.4f}, f_geo={:.4f}".format(*modis_red_brdf))
    print("Input MODIS NIR BRDF: f_iso={:.4f}, f_vol={:.4f}, f_geo={:.4f}".format(*modis_nir_brdf))
    print("Output Himawari Red BRDF: f_iso={:.4f}, f_vol={:.4f}, f_geo={:.4f}".format(*h8_red_brdf))
    print("Output Himawari NIR BRDF: f_iso={:.4f}, f_vol={:.4f}, f_geo={:.4f}".format(*h8_nir_brdf))

    # Prepare for full image processing
    print("\nReady for full image processing:")
    print("Required data:")
    print("1. MCD12Q1 land cover classification map (IGBP classes)")
    print("2. MCD43A1 BRDF Albedo product (containing f_iso, f_vol, f_geo parameters)")
