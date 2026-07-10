export const colors = {
  surface: "#090A0F",
  onSurface: "#F3F4F6",
  surfaceSecondary: "#11131A",
  onSurfaceSecondary: "#9CA3AF",
  surfaceTertiary: "#1A1D27",
  onSurfaceTertiary: "#D1D5DB",
  surfaceInverse: "#F3F4F6",
  onSurfaceInverse: "#090A0F",
  brand: "#00E5FF",
  brandSecondary: "#00B3CC",
  brandTertiary: "#00333D",
  onBrand: "#000000",
  success: "#39FF14",
  warning: "#FFB000",
  error: "#FF2A2A",
  info: "#00E5FF",
  border: "#262A36",
  borderStrong: "#00E5FF",
  divider: "#1A1D27",
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 };
export const radius = { sm: 4, md: 8, lg: 12, pill: 999 };

export const fonts = {
  display: "Rajdhani-SemiBold",
  displayBold: "Rajdhani-Bold",
  body: "SpaceGrotesk-Regular",
  bodyMedium: "SpaceGrotesk-Medium",
  mono: "IBMPlexMono-Regular",
  monoMedium: "IBMPlexMono-Medium",
};

export const fontSize = { sm: 12, base: 14, lg: 16, xl: 20, "2xl": 24, "3xl": 32 };

// Returns a threshold-based neon color: cyan -> amber -> red
export function metricColor(value: number | null | undefined): string {
  if (value == null) return colors.onSurfaceSecondary;
  if (value >= 85) return colors.error;
  if (value >= 70) return colors.warning;
  return colors.brand;
}
