import React, { useState, useCallback } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, ActivityIndicator, Platform } from "react-native";
import { useFocusEffect } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api, Alert } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/theme/theme";
import { ScreenTitle } from "@/src/components/common";

const ICONS: Record<Alert["type"], keyof typeof Ionicons.glyphMap> = {
  offline: "cloud-offline",
  online: "cloud-done",
  cpu: "hardware-chip",
  ram: "layers",
  updates: "arrow-up-circle",
};

function sevColor(sev: Alert["severity"]) {
  if (sev === "critical") return colors.error;
  if (sev === "warning") return colors.warning;
  return colors.brand;
}

function timeAgo(iso: string) {
  const d = new Date(iso).getTime();
  const diff = Math.floor((Date.now() - d) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function Alerts() {
  const insets = useSafeAreaInsets();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get<Alert[]>("/api/alerts");
      setAlerts(data);
    } catch {
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const clearAll = async () => {
    try {
      await api.del("/api/alerts");
      setAlerts([]);
    } catch {}
  };

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <View style={styles.headerRow}>
          <ScreenTitle eyebrow="INCIDENT LOG" title="Alerts" />
          {alerts.length > 0 && (
            <Pressable onPress={clearAll} style={styles.clearBtn} testID="clear-alerts-button">
              <Ionicons name="trash-outline" size={14} color={colors.onSurfaceSecondary} />
              <Text style={styles.clearText}>CLEAR</Text>
            </Pressable>
          )}
        </View>
      </View>

      {loading ? (
        <View style={styles.centerFill}>
          <ActivityIndicator color={colors.brand} />
        </View>
      ) : alerts.length === 0 ? (
        <View style={styles.centerFill} testID="alerts-empty">
          <Ionicons name="shield-checkmark-outline" size={64} color={colors.surfaceTertiary} />
          <Text style={styles.emptyTitle}>NO INCIDENTS DETECTED</Text>
          <Text style={styles.emptySub}>Alerts for offline nodes, CPU/RAM spikes and updates appear here.</Text>
        </View>
      ) : (
        <FlatList
          data={alerts}
          keyExtractor={(a) => a.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + 90 }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                load();
              }}
              tintColor={colors.brand}
            />
          }
          renderItem={({ item }) => {
            const c = sevColor(item.severity);
            return (
              <View style={styles.row} testID={`alert-${item.id}`}>
                <View style={[styles.node, { borderColor: c }]}>
                  <Ionicons name={ICONS[item.type]} size={16} color={c} />
                </View>
                <View style={styles.rowBody}>
                  <View style={styles.rowHead}>
                    <Text style={styles.serverName}>{item.server_name}</Text>
                    <Text style={styles.time}>{timeAgo(item.created_at)}</Text>
                  </View>
                  <Text style={styles.message}>{item.message}</Text>
                </View>
              </View>
            );
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end" },
  clearBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 6, paddingHorizontal: 10, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  clearText: { fontFamily: fonts.monoMedium, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 1 },
  centerFill: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, letterSpacing: 1.5, marginTop: spacing.lg },
  emptySub: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center", marginTop: spacing.sm },
  row: { flexDirection: "row", gap: spacing.md, marginBottom: spacing.md },
  node: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1.5,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSecondary,
  },
  rowBody: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  serverName: { fontFamily: fonts.display, fontSize: 16, color: colors.onSurface },
  time: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary },
  message: { fontFamily: fonts.body, fontSize: 13, color: colors.onSurfaceTertiary },
});
