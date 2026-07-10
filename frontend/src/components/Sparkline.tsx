import React from "react";
import { View, Text, StyleSheet } from "react-native";
import Svg, { Polyline, Path, Line } from "react-native-svg";

import { colors, fonts } from "@/src/theme/theme";

type Props = {
  data: (number | null)[];
  label: string;
  color: string;
  width?: number;
  height?: number;
  latest?: number | null;
  testID?: string;
};

// Sparkline for percentage metrics (0-100 domain).
export default function Sparkline({ data, label, color, width = 300, height = 64, latest, testID }: Props) {
  const points = data.filter((d): d is number => d != null);
  const enough = points.length >= 2;

  const pad = 3;
  const w = width;
  const h = height;

  let polyPoints = "";
  let areaPath = "";
  if (enough) {
    const n = data.length;
    const stepX = (w - pad * 2) / Math.max(1, n - 1);
    const coords = data.map((v, i) => {
      const x = pad + i * stepX;
      const val = v == null ? 0 : Math.max(0, Math.min(100, v));
      const y = h - pad - (val / 100) * (h - pad * 2);
      return { x, y, has: v != null };
    });
    const drawable = coords.filter((c) => c.has);
    polyPoints = drawable.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
    if (drawable.length) {
      areaPath =
        `M ${drawable[0].x.toFixed(1)} ${drawable[0].y.toFixed(1)} ` +
        drawable.slice(1).map((c) => `L ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ") +
        ` L ${drawable[drawable.length - 1].x.toFixed(1)} ${h - pad} L ${drawable[0].x.toFixed(1)} ${h - pad} Z`;
    }
  }

  return (
    <View style={styles.wrap} testID={testID}>
      <View style={styles.head}>
        <Text style={styles.label}>{label}</Text>
        <Text style={[styles.latest, { color }]}>{latest == null ? "--" : `${Math.round(latest)}%`}</Text>
      </View>
      <View style={{ width: w, height: h }}>
        <Svg width={w} height={h}>
          {/* baseline grid */}
          {[0.25, 0.5, 0.75].map((f) => (
            <Line key={f} x1={pad} y1={h * f} x2={w - pad} y2={h * f} stroke={colors.surfaceTertiary} strokeWidth={0.5} />
          ))}
          {enough ? (
            <>
              <Path d={areaPath} fill={color} fillOpacity={0.12} />
              <Polyline points={polyPoints} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            </>
          ) : null}
        </Svg>
        {!enough && (
          <View style={styles.emptyOverlay}>
            <Text style={styles.emptyText}>Collecting data…</Text>
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginBottom: 12 },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  label: { fontFamily: fonts.monoMedium, fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 1.5 },
  latest: { fontFamily: fonts.monoMedium, fontSize: 13 },
  emptyOverlay: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  emptyText: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary },
});
