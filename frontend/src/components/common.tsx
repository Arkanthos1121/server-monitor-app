import React from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ViewStyle,
  TextStyle,
} from "react-native";
import * as Haptics from "expo-haptics";
import { Platform } from "react-native";

import { colors, fonts, radius, spacing } from "@/src/theme/theme";

export function StatusDot({ online, size = 10 }: { online: boolean; size?: number }) {
  const c = online ? colors.success : colors.error;
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: c,
        shadowColor: c,
        shadowOpacity: 0.9,
        shadowRadius: 6,
        shadowOffset: { width: 0, height: 0 },
        elevation: 4,
      }}
    />
  );
}

export function Bar({ value, color }: { value: number | null; color: string }) {
  return (
    <View style={styles.barTrack}>
      <View
        style={{
          width: `${value == null ? 0 : Math.min(100, value)}%`,
          height: "100%",
          backgroundColor: color,
          borderRadius: radius.sm,
        }}
      />
    </View>
  );
}

type BtnProps = {
  title: string;
  onPress: () => void;
  variant?: "primary" | "outline" | "danger" | "ghost";
  loading?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
  style?: ViewStyle;
  testID?: string;
};

export function NeonButton({
  title,
  onPress,
  variant = "primary",
  loading,
  disabled,
  icon,
  style,
  testID,
}: BtnProps) {
  const handle = () => {
    if (disabled || loading) return;
    if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onPress();
  };
  const isPrimary = variant === "primary";
  const isDanger = variant === "danger";
  const isOutline = variant === "outline";
  const bg = isPrimary ? colors.brand : isDanger ? colors.error : "transparent";
  const fg = isPrimary
    ? colors.onBrand
    : isDanger
    ? "#fff"
    : isOutline
    ? colors.brand
    : colors.onSurfaceSecondary;
  const border = isOutline ? colors.brand : "transparent";

  return (
    <Pressable
      testID={testID}
      onPress={handle}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, borderColor: border, borderWidth: isOutline ? 1.5 : 0, opacity: disabled ? 0.5 : pressed ? 0.85 : 1 },
        isPrimary && {
          shadowColor: colors.brand,
          shadowOpacity: 0.5,
          shadowRadius: 12,
          shadowOffset: { width: 0, height: 0 },
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <View style={styles.btnRow}>
          {icon}
          <Text style={[styles.btnText, { color: fg }]}>{title}</Text>
        </View>
      )}
    </Pressable>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function ScreenTitle({ eyebrow, title, style }: { eyebrow?: string; title: string; style?: TextStyle }) {
  return (
    <View>
      {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
      <Text style={[styles.screenTitle, style]}>{title}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  barTrack: {
    height: 6,
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.sm,
    overflow: "hidden",
    width: "100%",
  },
  btn: {
    height: 52,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
  },
  btnRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  btnText: { fontFamily: fonts.displayBold, fontSize: 16, letterSpacing: 1, textTransform: "uppercase" },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  eyebrow: {
    fontFamily: fonts.monoMedium,
    fontSize: 11,
    color: colors.brand,
    letterSpacing: 2,
    textTransform: "uppercase",
    marginBottom: 4,
  },
  screenTitle: { fontFamily: fonts.displayBold, fontSize: 28, color: colors.onSurface, letterSpacing: 0.5 },
});
