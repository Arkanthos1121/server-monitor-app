import React, { useState, useEffect } from "react";
import { View, Text, StyleSheet, TextInput, Pressable, Switch, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";
import { Ionicons } from "@expo/vector-icons";

import { api, Server, ApiError } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/theme/theme";
import { NeonButton } from "@/src/components/common";

export default function AddServer() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const isEdit = !!id;

  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("10000");
  const [username, setUsername] = useState("root");
  const [password, setPassword] = useState("");
  const [useSsl, setUseSsl] = useState(true);
  const [verifyCert, setVerifyCert] = useState(false);
  const [checkMode, setCheckMode] = useState<"webmin" | "tcp" | "ping">("webmin");
  const [origMode, setOrigMode] = useState<"webmin" | "tcp" | "ping" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isEdit) return;
    (async () => {
      try {
        const s = await api.get<Server>(`/api/servers/${id}`);
        setName(s.name);
        setHost(s.host);
        setPort(String(s.port));
        setUsername(s.username);
        setUseSsl(s.use_ssl);
        setVerifyCert(s.verify_cert);
        setCheckMode(s.check_mode);
        setOrigMode(s.check_mode);
      } catch {}
    })();
  }, [id, isEdit]);

  const save = async () => {
    setError(null);
    if (!name.trim() || !host.trim()) {
      setError("Name and host are required");
      return;
    }
    if (checkMode === "webmin" && !password && (!isEdit || origMode !== "webmin")) {
      setError("Password is required for Webmin checks");
      return;
    }
    setSaving(true);
    try {
      const portNum = parseInt(port, 10) || 10000;
      if (isEdit) {
        const body: any = {
          name: name.trim(),
          host: host.trim(),
          port: portNum,
          username: username.trim() || "root",
          use_ssl: useSsl,
          verify_cert: verifyCert,
          check_mode: checkMode,
        };
        if (password) body.password = password;
        await api.put(`/api/servers/${id}`, body);
      } else {
        await api.post("/api/servers", {
          name: name.trim(),
          host: host.trim(),
          port: portNum,
          username: username.trim() || "root",
          password,
          use_ssl: useSsl,
          verify_cert: verifyCert,
          check_mode: checkMode,
        });
      }
      router.back();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save server");
    } finally {
      setSaving(false);
    }
  };

  const MODES: { key: "webmin" | "tcp" | "ping"; label: string; hint: string }[] = [
    { key: "webmin", label: "WEBMIN", hint: "Full HTTP(S) check: online + CPU/RAM + updates" },
    { key: "tcp", label: "TCP PORT", hint: "Just checks the port is open (fast, no login)" },
    { key: "ping", label: "PING", hint: "ICMP ping — is the host alive on the network" },
  ];
  const modeHint = MODES.find((m) => m.key === checkMode)?.hint || "";

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="close-add-button">
          <Ionicons name="close" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>{isEdit ? "EDIT NODE" : "ADD NODE"}</Text>
        <View style={{ width: 26 }} />
      </View>

      <KeyboardAwareScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: 40 }}
        bottomOffset={90}
        showsVerticalScrollIndicator={false}
      >
        <Field label="DISPLAY NAME" value={name} onChangeText={setName} placeholder="Production DB" autoCapitalize="words" testID="name-input" />
        <Field label="HOST / IP" value={host} onChangeText={setHost} placeholder="192.168.1.10 or srv.domain.com" autoCapitalize="none" keyboardType="url" testID="host-input" />
        <Field label={checkMode === "ping" ? "PORT (unused for ping)" : "PORT"} value={port} onChangeText={setPort} placeholder="10000" keyboardType="number-pad" testID="port-input" />

        <View style={styles.field}>
          <Text style={styles.fieldLabel}>CHECK MODE</Text>
          <View style={styles.segment}>
            {MODES.map((m) => {
              const active = checkMode === m.key;
              return (
                <Pressable
                  key={m.key}
                  testID={`mode-${m.key}`}
                  onPress={() => setCheckMode(m.key)}
                  style={[styles.segmentItem, active && styles.segmentItemActive]}
                >
                  <Text style={[styles.segmentText, active && styles.segmentTextActive]}>{m.label}</Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={styles.sslHint}>{modeHint}</Text>
        </View>

        {checkMode === "webmin" && (
          <>
            <Field label="WEBMIN USERNAME" value={username} onChangeText={setUsername} placeholder="root" autoCapitalize="none" testID="username-input" />
            <Field
              label={isEdit ? "PASSWORD (leave blank to keep)" : "WEBMIN PASSWORD"}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              secureTextEntry
              testID="password-input"
            />

            <View style={styles.sslRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.sslLabel}>USE HTTPS</Text>
                <Text style={styles.sslHint}>Webmin uses HTTPS by default (self-signed OK)</Text>
              </View>
              <Switch
                testID="ssl-toggle"
                value={useSsl}
                onValueChange={setUseSsl}
                trackColor={{ true: colors.brandTertiary, false: colors.surfaceTertiary }}
                thumbColor={useSsl ? colors.brand : colors.onSurfaceSecondary}
              />
            </View>

            {useSsl && (
              <View style={[styles.sslRow, { marginTop: spacing.md }]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.sslLabel}>VERIFY TLS CERTIFICATE</Text>
                  <Text style={styles.sslHint}>Enable only if this server has a valid (non-self-signed) cert</Text>
                </View>
                <Switch
                  testID="verify-cert-toggle"
                  value={verifyCert}
                  onValueChange={setVerifyCert}
                  trackColor={{ true: colors.brandTertiary, false: colors.surfaceTertiary }}
                  thumbColor={verifyCert ? colors.brand : colors.onSurfaceSecondary}
                />
              </View>
            )}
          </>
        )}

        {error ? (
          <Text style={styles.error} testID="add-error">
            {"> "}
            {error}
          </Text>
        ) : null}
      </KeyboardAwareScrollView>

      <KeyboardStickyView offset={{ closed: 0, opened: insets.bottom }}>
        <View style={[styles.sticky, { paddingBottom: insets.bottom + spacing.md }]}>
          <NeonButton
            title={saving ? "Connecting..." : isEdit ? "Save Changes" : "Save & Connect"}
            onPress={save}
            loading={saving}
            testID="save-server-button"
          />
        </View>
      </KeyboardStickyView>
    </View>
  );
}

function Field({
  label,
  testID,
  ...props
}: { label: string; testID?: string } & React.ComponentProps<typeof TextInput>) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={styles.field}>
      <Text style={[styles.fieldLabel, focused && { color: colors.brand }]}>{label}</Text>
      <TextInput
        testID={testID}
        placeholderTextColor={colors.onSurfaceSecondary}
        style={[styles.input, focused && { borderColor: colors.brand }]}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        {...props}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, letterSpacing: 2 },
  field: { marginBottom: spacing.lg },
  fieldLabel: { fontFamily: fonts.monoMedium, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 1.5, marginBottom: 6 },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 50,
    color: colors.onSurface,
    fontFamily: fonts.mono,
    fontSize: 14,
  },
  sslRow: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md },
  sslLabel: { fontFamily: fonts.monoMedium, fontSize: 12, color: colors.onSurface, letterSpacing: 1 },
  sslHint: { fontFamily: fonts.body, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  segment: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.sm },
  segmentItem: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary, alignItems: "center" },
  segmentItemActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  segmentText: { fontFamily: fonts.monoMedium, fontSize: 11, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  segmentTextActive: { color: colors.onBrand },
  error: { fontFamily: fonts.mono, fontSize: 12, color: colors.error, marginTop: spacing.sm },
  sticky: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
});
