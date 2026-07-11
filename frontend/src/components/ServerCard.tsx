import React from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { Server } from "@/src/lib/api";
import { colors, fonts, radius, spacing, metricColor } from "@/src/theme/theme";
import { StatusDot, Bar } from "@/src/components/common";

export default function ServerCard({ server, onPress }: { server: Server; onPress: () => void }) {
  const st = server.last_status;
  const online = !!st?.online;
  const updates = st?.updates ?? null;
  const isWebmin = server.check_mode === "webmin";
  const authFailed = isWebmin && online && st?.auth_ok === false;

  const handle = () => {
    if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onPress();
  };

  return (
    <Pressable
      testID={`server-card-${server.id}`}
      onPress={handle}
      style={({ pressed }) => [
        styles.card,
        { borderColor: online ? colors.border : colors.error, opacity: pressed ? 0.85 : 1 },
      ]}
    >
      <View style={styles.topRow}>
        <StatusDot online={online} />
        {updates != null && updates > 0 ? (
          <View style={styles.updateBadge}>
            <Ionicons name="arrow-up-circle" size={12} color={colors.warning} />
            <Text style={styles.updateText}>{updates}</Text>
          </View>
        ) : (
          <View />
        )}
      </View>

      <Text style={styles.name} numberOfLines={1}>
        {server.name}
      </Text>
      <Text style={styles.host} numberOfLines={1}>
        {server.host}:{server.port}
      </Text>

      {online ? (
        isWebmin ? (
          <View style={styles.metrics}>
            {authFailed && (
              <View style={styles.authFail}>
                <Ionicons name="lock-closed" size={11} color={colors.warning} />
                <Text style={styles.authFailText}>AUTH FAILED</Text>
              </View>
            )}
            <MetricRow label="CPU" value={st?.cpu ?? null} />
            <MetricRow label="RAM" value={st?.ram ?? null} />
          </View>
        ) : (
          <View style={styles.onlineBox}>
            <Ionicons name="checkmark-circle" size={14} color={colors.success} />
            <Text style={styles.onlineText}>{server.check_mode === "ping" ? "PING OK" : "PORT OPEN"}</Text>
          </View>
        )
      ) : (
        <View style={styles.offlineBox}>
          <Text style={styles.offlineText}>OFFLINE</Text>
        </View>
      )}
    </Pressable>
  );
}

function MetricRow({ label, value }: { label: string; value: number | null }) {
  const c = metricColor(value);
  return (
    <View style={styles.metricRow}>
      <View style={styles.metricHead}>
        <Text style={styles.metricLabel}>{label}</Text>
        <Text style={[styles.metricValue, { color: c }]}>{value == null ? "--" : `${Math.round(value)}%`}</Text>
      </View>
      <Bar value={value} color={c} />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: spacing.md,
    minHeight: 150,
  },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  updateBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: colors.surfaceTertiary,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  updateText: { fontFamily: fonts.monoMedium, fontSize: 11, color: colors.warning },
  name: { fontFamily: fonts.display, fontSize: 18, color: colors.onSurface },
  host: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2, marginBottom: spacing.md },
  metrics: { gap: spacing.sm, marginTop: "auto" },
  metricRow: { gap: 4 },
  metricHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  metricLabel: { fontFamily: fonts.monoMedium, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 1 },
  metricValue: { fontFamily: fonts.monoMedium, fontSize: 12 },
  offlineBox: {
    marginTop: "auto",
    borderWidth: 1,
    borderColor: colors.error,
    borderRadius: radius.sm,
    paddingVertical: spacing.sm,
    alignItems: "center",
  },
  offlineText: { fontFamily: fonts.monoMedium, fontSize: 12, color: colors.error, letterSpacing: 2 },
  onlineBox: {
    marginTop: "auto",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.success,
    borderRadius: radius.sm,
    paddingVertical: spacing.sm,
  },
  onlineText: { fontFamily: fonts.monoMedium, fontSize: 12, color: colors.success, letterSpacing: 2 },
  authFail: { flexDirection: "row", alignItems: "center", gap: 4, marginBottom: 2 },
  authFailText: { fontFamily: fonts.monoMedium, fontSize: 9, color: colors.warning, letterSpacing: 1 },
});
