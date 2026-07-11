import React, { useState, useEffect } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Switch, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/context/AuthContext";
import { api, User } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/theme/theme";
import { ScreenTitle, NeonButton } from "@/src/components/common";

function Stepper({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <View style={styles.stepRow}>
      <Text style={styles.rowLabel}>{label}</Text>
      <View style={styles.stepper}>
        <Pressable style={styles.stepBtn} onPress={() => onChange(Math.max(50, value - 5))} testID={`${label}-minus`}>
          <Ionicons name="remove" size={18} color={colors.brand} />
        </Pressable>
        <Text style={styles.stepValue}>{value}%</Text>
        <Pressable style={styles.stepBtn} onPress={() => onChange(Math.min(99, value + 5))} testID={`${label}-plus`}>
          <Ionicons name="add" size={18} color={colors.brand} />
        </Pressable>
      </View>
    </View>
  );
}

export default function Settings() {
  const insets = useSafeAreaInsets();
  const { user, logout, refreshUser } = useAuth();
  const [cpu, setCpu] = useState(user?.cpu_threshold ?? 85);
  const [ram, setRam] = useState(user?.ram_threshold ?? 85);
  const [alertsEnabled, setAlertsEnabled] = useState(user?.alerts_enabled ?? true);
  const [pollInterval, setPollInterval] = useState(user?.poll_interval_minutes ?? 30);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(false);

  // Keep local controls in sync if the user object loads/changes after mount.
  useEffect(() => {
    if (!user) return;
    setCpu(user.cpu_threshold);
    setRam(user.ram_threshold);
    setAlertsEnabled(user.alerts_enabled);
    setPollInterval(user.poll_interval_minutes);
  }, [user]);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    setSaveError(false);
    try {
      await api.put<User>("/api/settings", {
        cpu_threshold: cpu,
        ram_threshold: ram,
        alerts_enabled: alertsEnabled,
        poll_interval_minutes: pollInterval,
      });
      await refreshUser();
      setSaved(true);
    } catch {
      setSaveError(true);
    } finally {
      setSaving(false);
    }
  };

  const POLL_OPTIONS = [5, 15, 30, 60];

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={{ padding: spacing.lg, paddingTop: insets.top + spacing.md, paddingBottom: insets.bottom + 100 }}
    >
      <ScreenTitle eyebrow="CONFIGURATION" title="System" />

      <View style={styles.section}>
        <View style={styles.accountRow}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{(user?.name || user?.email || "?")[0]?.toUpperCase()}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.accountName}>{user?.name || "Operator"}</Text>
            <Text style={styles.accountEmail}>{user?.email}</Text>
          </View>
        </View>
      </View>

      <Text style={styles.sectionTitle}>ALERT THRESHOLDS</Text>
      <View style={styles.section}>
        <View style={styles.toggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.rowLabel}>Push Alerts</Text>
            <Text style={styles.rowHint}>Notify on offline, high CPU/RAM & updates</Text>
          </View>
          <Switch
            testID="alerts-toggle"
            value={alertsEnabled}
            onValueChange={setAlertsEnabled}
            trackColor={{ true: colors.brandTertiary, false: colors.surfaceTertiary }}
            thumbColor={alertsEnabled ? colors.brand : colors.onSurfaceSecondary}
          />
        </View>
        <View style={styles.hr} />
        <Stepper label="CPU" value={cpu} onChange={setCpu} />
        <View style={styles.hr} />
        <Stepper label="RAM" value={ram} onChange={setRam} />
      </View>

      <Text style={styles.sectionTitle}>MONITORING</Text>
      <View style={styles.section}>
        <View style={styles.infoRow}>
          <Ionicons name="time-outline" size={18} color={colors.brand} />
          <Text style={styles.rowLabel}>Background Poll Interval</Text>
        </View>
        <View style={styles.segment}>
          {POLL_OPTIONS.map((opt) => {
            const active = pollInterval === opt;
            return (
              <Pressable
                key={opt}
                testID={`poll-${opt}`}
                onPress={() => setPollInterval(opt)}
                style={[styles.segmentItem, active && styles.segmentItemActive]}
              >
                <Text style={[styles.segmentText, active && styles.segmentTextActive]}>
                  {opt < 60 ? `${opt}m` : "1h"}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={styles.rowHint}>
          Servers are checked automatically every {pollInterval < 60 ? `${pollInterval} minutes` : "hour"}. Pull down on
          the grid for an instant refresh.
        </Text>
      </View>

      <NeonButton title={saved ? "Saved ✓" : "Save Settings"} onPress={save} loading={saving} testID="save-settings-button" style={{ marginTop: spacing.lg }} />
      {saveError ? (
        <Text style={styles.saveError} testID="settings-save-error">
          {"> "}Could not save settings. Check your connection and try again.
        </Text>
      ) : null}

      <Pressable style={styles.logout} onPress={logout} testID="logout-button">
        <Ionicons name="log-out-outline" size={18} color={colors.error} />
        <Text style={styles.logoutText}>DISCONNECT SESSION</Text>
      </Pressable>

      <Text style={styles.version}>WEBMINPULSE · v1.0.0</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  section: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  sectionTitle: { fontFamily: fonts.monoMedium, fontSize: 11, color: colors.brand, letterSpacing: 2, marginTop: spacing.xl },
  accountRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  avatar: { width: 48, height: 48, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.brand },
  accountName: { fontFamily: fonts.display, fontSize: 18, color: colors.onSurface },
  accountEmail: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  toggleRow: { flexDirection: "row", alignItems: "center", paddingVertical: spacing.sm },
  rowLabel: { fontFamily: fonts.bodyMedium, fontSize: 15, color: colors.onSurface },
  rowHint: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  hr: { height: 1, backgroundColor: colors.divider, marginVertical: spacing.sm },
  stepRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.sm },
  stepper: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  stepBtn: { width: 34, height: 34, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  stepValue: { fontFamily: fonts.monoMedium, fontSize: 16, color: colors.onSurface, minWidth: 44, textAlign: "center" },
  infoRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  infoValue: { fontFamily: fonts.monoMedium, fontSize: 13, color: colors.brand, marginLeft: "auto" },
  segment: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md, marginBottom: spacing.sm },
  segmentItem: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center" },
  segmentItemActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  segmentText: { fontFamily: fonts.monoMedium, fontSize: 14, color: colors.onSurfaceSecondary },
  segmentTextActive: { color: colors.onBrand },
  logout: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, marginTop: spacing.xl, paddingVertical: spacing.md, borderWidth: 1, borderColor: colors.error, borderRadius: radius.md },
  logoutText: { fontFamily: fonts.monoMedium, fontSize: 13, color: colors.error, letterSpacing: 1 },
  version: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary, textAlign: "center", marginTop: spacing.xl },
  saveError: { fontFamily: fonts.mono, fontSize: 12, color: colors.error, marginTop: spacing.sm },
});
