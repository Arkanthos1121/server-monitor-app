import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  Platform,
} from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { api, Server } from "@/src/lib/api";
import { colors, fonts, radius, spacing, metricColor } from "@/src/theme/theme";
import { NeonButton, StatusDot } from "@/src/components/common";
import Gauge from "@/src/components/Gauge";

export default function ServerDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [server, setServer] = useState<Server | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await api.get<Server>(`/api/servers/${id}`);
      setServer(s);
    } catch {
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      const s = await api.post<Server>(`/api/servers/${id}/check`);
      setServer(s);
    } catch {
    } finally {
      setRefreshing(false);
    }
  }, [id]);

  const openWebmin = () => {
    if (!server) return;
    if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push({ pathname: "/webview", params: { url: server.webmin_url, name: server.name } });
  };

  const doDelete = async () => {
    setConfirmDelete(false);
    try {
      await api.del(`/api/servers/${id}`);
      router.back();
    } catch {}
  };

  if (loading || !server) {
    return (
      <View style={styles.centerFill}>
        <ActivityIndicator color={colors.brand} />
      </View>
    );
  }

  const st = server.last_status;
  const online = !!st?.online;
  const updates = st?.updates ?? null;

  return (
    <View style={styles.root}>
      {/* Header */}
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <View style={styles.headerRow}>
          <Pressable onPress={() => router.back()} hitSlop={12} testID="back-button">
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={styles.headerActions}>
            <Pressable onPress={() => router.push({ pathname: "/server/add", params: { id: server.id } })} hitSlop={12} testID="edit-server-button">
              <Ionicons name="create-outline" size={22} color={colors.onSurfaceSecondary} />
            </Pressable>
            <Pressable onPress={() => setConfirmDelete(true)} hitSlop={12} testID="delete-server-button">
              <Ionicons name="trash-outline" size={22} color={colors.error} />
            </Pressable>
          </View>
        </View>
        <View style={styles.titleRow}>
          <StatusDot online={online} size={12} />
          <Text style={styles.title} numberOfLines={1}>
            {server.name}
          </Text>
        </View>
        <Text style={styles.host}>
          {server.host}:{server.port}
        </Text>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.brand} />}
      >
        {!online && (
          <View style={styles.offlineBanner} testID="offline-banner">
            <Ionicons name="warning" size={20} color={colors.error} />
            <Text style={styles.offlineText}>NODE UNREACHABLE — server is offline or credentials/port are wrong.</Text>
          </View>
        )}

        {/* Gauges */}
        <View style={styles.gauges}>
          <Gauge value={online ? st?.cpu ?? null : null} label="CPU" testID="cpu-gauge" />
          <Gauge value={online ? st?.ram ?? null : null} label="RAM" testID="ram-gauge" />
          <Gauge value={online ? st?.disk ?? null : null} label="DISK" testID="disk-gauge" />
        </View>

        {/* Telemetry */}
        <View style={styles.infoCard}>
          <InfoLine label="STATUS" value={online ? "ONLINE" : "OFFLINE"} color={online ? colors.success : colors.error} />
          <InfoLine label="UPTIME" value={st?.uptime || "—"} />
          <InfoLine
            label="LOAD AVG"
            value={st?.load && st.load.some((x) => x != null) ? st.load.map((x) => (x == null ? "—" : x.toFixed(2))).join("  ") : "—"}
          />
          <InfoLine label="LAST CHECK" value={st?.checked_at ? new Date(st.checked_at).toLocaleTimeString() : "—"} />
        </View>

        {/* Updates */}
        <Text style={styles.sectionTitle}>PACKAGE UPDATES</Text>
        <View style={styles.updatesCard}>
          {updates == null ? (
            <Text style={styles.updatesText}>Update status unavailable for this node.</Text>
          ) : updates === 0 ? (
            <View style={styles.updatesRow}>
              <Ionicons name="checkmark-circle" size={18} color={colors.success} />
              <Text style={[styles.updatesText, { color: colors.success }]}>All packages up to date</Text>
            </View>
          ) : (
            <View style={styles.updatesRow}>
              <Ionicons name="arrow-up-circle" size={18} color={colors.warning} />
              <Text style={[styles.updatesText, { color: colors.warning }]}>
                {updates} package update{updates > 1 ? "s" : ""} available
              </Text>
            </View>
          )}
        </View>
      </ScrollView>

      {/* Sticky open webmin */}
      <View style={[styles.sticky, { paddingBottom: insets.bottom + spacing.md }]}>
        <NeonButton
          title="Open Webmin Panel"
          onPress={openWebmin}
          testID="open-webmin-button"
          icon={<Ionicons name="open-outline" size={18} color={colors.onBrand} />}
        />
      </View>

      {/* Delete confirm */}
      <Modal visible={confirmDelete} transparent animationType="fade" onRequestClose={() => setConfirmDelete(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>DELETE NODE?</Text>
            <Text style={styles.modalBody}>Remove "{server.name}" and its alert history. This cannot be undone.</Text>
            <View style={styles.modalActions}>
              <NeonButton title="Cancel" variant="outline" onPress={() => setConfirmDelete(false)} style={{ flex: 1 }} testID="cancel-delete-button" />
              <NeonButton title="Delete" variant="danger" onPress={doDelete} style={{ flex: 1 }} testID="confirm-delete-button" />
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function InfoLine({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={styles.infoLine}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={[styles.infoValue, color && { color }]} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  centerFill: { flex: 1, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  headerActions: { flexDirection: "row", gap: spacing.lg },
  titleRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 26, color: colors.onSurface, flex: 1 },
  host: { fontFamily: fonts.mono, fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 2 },
  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.error,
    backgroundColor: "rgba(255,42,42,0.08)",
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  offlineText: { fontFamily: fonts.body, fontSize: 13, color: colors.error, flex: 1 },
  gauges: { flexDirection: "row", justifyContent: "space-between", marginVertical: spacing.md },
  infoCard: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, paddingHorizontal: spacing.md, marginTop: spacing.md },
  infoLine: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider },
  infoLabel: { fontFamily: fonts.monoMedium, fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 1.5 },
  infoValue: { fontFamily: fonts.monoMedium, fontSize: 13, color: colors.onSurface, maxWidth: "60%" },
  sectionTitle: { fontFamily: fonts.monoMedium, fontSize: 11, color: colors.brand, letterSpacing: 2, marginTop: spacing.xl, marginBottom: spacing.sm },
  updatesCard: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.md },
  updatesRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  updatesText: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary },
  sticky: { position: "absolute", left: 0, right: 0, bottom: 0, paddingHorizontal: spacing.lg, paddingTop: spacing.md, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center", padding: spacing.xl },
  modalCard: { width: "100%", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.lg },
  modalTitle: { fontFamily: fonts.displayBold, fontSize: 20, color: colors.onSurface, letterSpacing: 1 },
  modalBody: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary, marginTop: spacing.sm, marginBottom: spacing.lg },
  modalActions: { flexDirection: "row", gap: spacing.md },
});
