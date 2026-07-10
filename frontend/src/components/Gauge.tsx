import React, { useEffect } from "react";
import { View, Text, StyleSheet } from "react-native";
import Svg, { Circle } from "react-native-svg";
import Animated, {
  useSharedValue,
  useAnimatedProps,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { colors, fonts, metricColor } from "@/src/theme/theme";

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

type Props = {
  value: number | null;
  label: string;
  size?: number;
  strokeWidth?: number;
  testID?: string;
};

export default function Gauge({ value, label, size = 104, strokeWidth = 9, testID }: Props) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = useSharedValue(0);
  const active = value != null;
  const color = metricColor(value);

  useEffect(() => {
    progress.value = withTiming(active ? Math.min(100, value as number) / 100 : 0, {
      duration: 900,
      easing: Easing.out(Easing.cubic),
    });
  }, [value, active, progress]);

  const animatedProps = useAnimatedProps(() => ({
    strokeDashoffset: circumference * (1 - progress.value),
  }));

  return (
    <View style={[styles.wrap, { width: size }]} testID={testID}>
      <View style={{ width: size, height: size }}>
        <Svg width={size} height={size}>
          <Circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={colors.surfaceTertiary}
            strokeWidth={strokeWidth}
            fill="none"
          />
          <AnimatedCircle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={color}
            strokeWidth={strokeWidth}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={circumference}
            animatedProps={animatedProps}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        </Svg>
        <View style={styles.center}>
          <Text style={[styles.value, { color }]}>{active ? `${Math.round(value as number)}` : "--"}</Text>
          <Text style={styles.pct}>{active ? "%" : ""}</Text>
        </View>
      </View>
      <Text style={styles.label}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center" },
  center: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", flexDirection: "row" },
  value: { fontFamily: fonts.displayBold, fontSize: 30, includeFontPadding: false },
  pct: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 6, marginLeft: 1 },
  label: {
    fontFamily: fonts.monoMedium,
    fontSize: 11,
    color: colors.onSurfaceSecondary,
    letterSpacing: 1.5,
    marginTop: 8,
    textTransform: "uppercase",
  },
});
