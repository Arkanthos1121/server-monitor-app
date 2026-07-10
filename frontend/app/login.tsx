import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  Pressable,
  Platform,
  useWindowDimensions,
} from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/context/AuthContext";
import { colors, fonts, radius, spacing } from "@/src/theme/theme";
import { NeonButton } from "@/src/components/common";
import { ApiError } from "@/src/lib/api";

const HERO =
  "https://images.unsplash.com/photo-1532190872407-280735d27e08?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1Nzh8MHwxfHNlYXJjaHwyfHxhYnN0cmFjdCUyMGRhcmslMjBmdXR1cmlzdGljJTIwZ2xvd2luZyUyMHRlY2glMjBiYWNrZ3JvdW5kfGVufDB8fHx8MTc4MzcyNDE5OHww&ixlib=rb-4.1.0&q=85";

export default function Login() {
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  const router = useRouter();
  const { user, login, register, loginWithGoogle } = useAuth();

  useEffect(() => {
    if (user) router.replace("/(tabs)");
  }, [user, router]);

  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [gLoading, setGLoading] = useState(false);

  const submit = async () => {
    setError(null);
    if (!email.trim() || !password) {
      setError("Email and password are required");
      return;
    }
    setLoading(true);
    try {
      if (mode === "login") await login(email.trim(), password);
      else await register(email.trim(), password, name.trim() || undefined);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const google = async () => {
    setError(null);
    setGLoading(true);
    try {
      await loginWithGoogle();
    } catch (e) {
      setError("Google sign-in failed");
    } finally {
      setGLoading(false);
    }
  };

  return (
    <View style={styles.root}>
      <Image source={{ uri: HERO }} style={StyleSheet.absoluteFill} contentFit="cover" />
      <LinearGradient
        colors={["rgba(9,10,15,0.4)", "rgba(9,10,15,0.85)", colors.surface]}
        locations={[0, 0.5, 1]}
        style={StyleSheet.absoluteFill}
      />
      <KeyboardAwareScrollView
        contentContainerStyle={[styles.scroll, { paddingTop: height * 0.16, paddingBottom: insets.bottom + 40 }]}
        bottomOffset={20}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.brandRow}>
          <Ionicons name="pulse" size={30} color={colors.brand} />
          <Text style={styles.brand}>
            WEBMIN<Text style={{ color: colors.brand }}>PULSE</Text>
          </Text>
        </View>
        <Text style={styles.tagline}>INFRASTRUCTURE COMMAND CENTER</Text>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>{mode === "login" ? "ACCESS TERMINAL" : "CREATE ACCESS"}</Text>

          {mode === "signup" && (
            <Field label="NAME" value={name} onChangeText={setName} placeholder="Commander" autoCapitalize="words" testID="name-input" />
          )}
          <Field
            label="EMAIL"
            value={email}
            onChangeText={setEmail}
            placeholder="you@domain.com"
            keyboardType="email-address"
            autoCapitalize="none"
            testID="email-input"
          />
          <Field
            label="PASSWORD"
            value={password}
            onChangeText={setPassword}
            placeholder="••••••••"
            secureTextEntry
            testID="password-input"
          />

          {error ? (
            <Text style={styles.error} testID="auth-error">
              {"> "}{error}
            </Text>
          ) : null}

          <NeonButton
            title={mode === "login" ? "Authenticate" : "Register"}
            onPress={submit}
            loading={loading}
            testID="submit-auth-button"
            style={{ marginTop: spacing.md }}
          />

          <View style={styles.divider}>
            <View style={styles.line} />
            <Text style={styles.orText}>OR</Text>
            <View style={styles.line} />
          </View>

          <NeonButton
            title="Continue with Google"
            variant="outline"
            onPress={google}
            loading={gLoading}
            testID="google-login-button"
            icon={<Ionicons name="logo-google" size={18} color={colors.brand} />}
          />

          <Pressable
            onPress={() => {
              setError(null);
              setMode(mode === "login" ? "signup" : "login");
            }}
            style={styles.switch}
            testID="toggle-mode-button"
          >
            <Text style={styles.switchText}>
              {mode === "login" ? "No access? " : "Have access? "}
              <Text style={{ color: colors.brand }}>{mode === "login" ? "REGISTER" : "SIGN IN"}</Text>
            </Text>
          </Pressable>
        </View>
      </KeyboardAwareScrollView>
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
  scroll: { paddingHorizontal: spacing.lg },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, justifyContent: "center" },
  brand: { fontFamily: fonts.displayBold, fontSize: 30, color: colors.onSurface, letterSpacing: 2 },
  tagline: {
    fontFamily: fonts.mono,
    fontSize: 11,
    color: colors.onSurfaceSecondary,
    letterSpacing: 3,
    textAlign: "center",
    marginTop: 6,
    marginBottom: spacing["2xl"],
  },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  cardTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 20,
    color: colors.onSurface,
    letterSpacing: 1.5,
    marginBottom: spacing.md,
  },
  field: { marginBottom: spacing.md },
  fieldLabel: { fontFamily: fonts.monoMedium, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 1.5, marginBottom: 6 },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 48,
    color: colors.onSurface,
    fontFamily: fonts.mono,
    fontSize: 14,
  },
  error: { fontFamily: fonts.mono, fontSize: 12, color: colors.error, marginTop: spacing.sm },
  divider: { flexDirection: "row", alignItems: "center", marginVertical: spacing.lg, gap: spacing.md },
  line: { flex: 1, height: 1, backgroundColor: colors.border },
  orText: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary },
  switch: { marginTop: spacing.lg, alignItems: "center" },
  switchText: { fontFamily: fonts.bodyMedium, fontSize: 13, color: colors.onSurfaceSecondary },
});
