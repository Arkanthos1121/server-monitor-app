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
      } catch {}
    })();
  }, [id, isEdit]);

  const save = async () => {
    setError(null);
    if (!name.trim() || !host.trim() || !username.trim()) {
      setError("Name, host and username are required");
      return;
    }
    if (!isEdit && !password) {
      setError("Password is required");
      return;
    }
    setSaving(true);
    try {
      const portNum = parseInt(port, 10) || 10000;
      if (isEdit) {
        const body: any = { name: name.trim(), host: host.trim(), port: portNum, username: username.trim(), use_ssl: useSsl, verify_cert: verifyCert };
        if (password) body.password = password;
        await api.put(`/api/servers/${id}`, body);
      } else {
        await api.post("/api/servers", {
          name: name.trim(),
          host: host.trim(),
          port: portNum,
          username: username.trim(),
          password,
          use_ssl: useSsl,
          verify_cert: verifyCert,
        });
      }
      router.back();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save server");
    } finally {
      setSaving(false);
    }
  };

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
        <Field label="PORT" value={port} onChangeText={setPort} placeholder="10000" keyboardType="number-pad" testID="port-input" />
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
  error: { fontFamily: fonts.mono, fontSize: 12, color: colors.error, marginTop: spacing.sm },
  sticky: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
});
