import React, { useState, useEffect } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Platform } from "react-native";
import { WebView } from "react-native-webview";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Linking from "expo-linking";

import { colors, fonts, radius, spacing } from "@/src/theme/theme";
import { NeonButton } from "@/src/components/common";

export default function WebminView() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { url, name } = useLocalSearchParams<{ url: string; name: string }>();
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (Platform.OS === "web" && url) {
      Linking.openURL(url);
      router.back();
    }
  }, [url, router]);

  const openExternal = () => {
    if (url) Linking.openURL(url);
  };

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="webview-close">
          <Ionicons name="close" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title} numberOfLines={1}>
          {name || "Webmin"}
        </Text>
        <Pressable onPress={openExternal} hitSlop={12} testID="webview-external">
          <Ionicons name="open-outline" size={22} color={colors.brand} />
        </Pressable>
      </View>

      {Platform.OS !== "web" && url ? (
        <View style={{ flex: 1 }}>
          <WebView
            source={{ uri: url }}
            style={{ flex: 1, backgroundColor: colors.surface }}
            onLoadEnd={() => setLoading(false)}
            onError={() => {
              setLoading(false);
              setFailed(true);
            }}
            onHttpError={() => setLoading(false)}
            startInLoadingState
          />
          {loading && !failed && (
            <View style={styles.overlay}>
              <ActivityIndicator color={colors.brand} />
              <Text style={styles.loadingText}>ESTABLISHING SECURE LINK...</Text>
            </View>
          )}
          {failed && (
            <View style={styles.overlay} testID="webview-failed">
              <Ionicons name="cloud-offline-outline" size={56} color={colors.error} />
              <Text style={styles.failTitle}>CONNECTION FAILED</Text>
              <Text style={styles.failSub}>
                The Webmin panel could not be loaded in-app (often due to self-signed certificates). Open it in your
                browser to accept the certificate.
              </Text>
              <NeonButton title="Open in Browser" onPress={openExternal} style={{ marginTop: spacing.lg }} testID="open-browser-button" />
            </View>
          )}
        </View>
      ) : (
        <View style={styles.overlay}>
          <ActivityIndicator color={colors.brand} />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: spacing.md,
  },
  title: { flex: 1, fontFamily: fonts.display, fontSize: 18, color: colors.onSurface, textAlign: "center" },
  overlay: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: spacing.xl },
  loadingText: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.md, letterSpacing: 2 },
  failTitle: { fontFamily: fonts.displayBold, fontSize: 20, color: colors.error, letterSpacing: 1, marginTop: spacing.lg },
  failSub: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center", marginTop: spacing.sm },
});
