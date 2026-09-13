import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable, Linking, Switch, ActivityIndicator,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";

import { api, ApiError, DedicatedGame, SteamScan } from "@/src/lib/api";
import { colors, fonts, fontSize, radius, spacing } from "@/src/theme/theme";
import { Card, NeonButton, ScreenTitle } from "@/src/components/common";

const KEY_URL = "https://steamcommunity.com/dev/apikey";

function hours(min: number) {
  if (!min) return "never played";
  if (min < 60) return `${min}m`;
  return `${Math.round(min / 60)}h`;
}

function HostLine({ g }: { g: DedicatedGame }) {
  if (g.bundled) return <Text style={styles.how}>Server ships with the game</Text>;
  if (g.server_appid) return <Text style={styles.how}>SteamCMD app {g.server_appid}</Text>;
  return <Text style={styles.how}>Listed in the Steam server browser</Text>;
}

export default function SteamScreen() {
  const insets = useSafeAreaInsets();
  const [apiKey, setApiKey] = useState("");
  const [steamId, setSteamId] = useState("");
  const [deep, setDeep] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scan, setScan] = useState<SteamScan | null>(null);
  const [loadingCached, setLoadingCached] = useState(true);

  // Show the last scan straight away so the key only has to be entered once.
  useEffect(() => {
    (async () => {
      try {
        const cached = await api.get<SteamScan>("/api/steam/scan");
        setScan(cached);
        if (cached.steamid) setSteamId(cached.steamid);
      } catch {
        /* no scan yet - that's the normal first-run case */
      } finally {
        setLoadingCached(false);
      }
    })();
  }, []);

  const runScan = async () => {
    setScanning(true);
    setError(null);
    try {
      const result = await api.post<SteamScan>("/api/steam/scan", {
        api_key: apiKey.trim(),
        steamid: steamId.trim(),
        deep,
      });
      setScan(result);
      setApiKey(""); // don't leave the credential sitting in the input
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan failed. Check the key and try again.");
    } finally {
      setScanning(false);
    }
  };

  const canScan = apiKey.trim().length > 10 && steamId.trim().length > 0 && !scanning;
  const hits = scan?.dedicated_capable ?? [];

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="steam-back">
          <Ionicons name="chevron-back" size={26} color={colors.brand} />
        </Pressable>
        <ScreenTitle eyebrow="STEAM" title="DEDICATED SERVERS" />
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + spacing["3xl"] }}
        keyboardShouldPersistTaps="handled"
      >
        <Card>
          <Text style={styles.cardTitle}>SCAN YOUR LIBRARY</Text>
          <Text style={styles.help}>
            Steam only hands a library over to an API key issued by your own account. It takes
            about thirty seconds to make one, and it works even if your profile is private.
          </Text>
          <Pressable onPress={() => Linking.openURL(KEY_URL)} testID="steam-key-link">
            <Text style={styles.link}>Get a key at steamcommunity.com/dev/apikey ↗</Text>
          </Pressable>
          <Text style={styles.help}>
            Any domain name works in the box — it is only a label.
          </Text>

          <Text style={styles.label}>STEAM API KEY</Text>
          <TextInput
            style={styles.input}
            value={apiKey}
            onChangeText={setApiKey}
            placeholder="ABC123..."
            placeholderTextColor={colors.onSurfaceSecondary}
            autoCapitalize="characters"
            autoCorrect={false}
            secureTextEntry
            testID="steam-api-key"
          />

          <Text style={styles.label}>STEAMID64 / PROFILE URL</Text>
          <TextInput
            style={styles.input}
            value={steamId}
            onChangeText={setSteamId}
            placeholder="76561198..."
            placeholderTextColor={colors.onSurfaceSecondary}
            autoCapitalize="none"
            autoCorrect={false}
            testID="steam-steamid"
          />

          <View style={styles.switchRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowLabel}>Deep scan</Text>
              <Text style={styles.helpTight}>
                Also probes games outside the catalog. Slower, finds more.
              </Text>
            </View>
            <Switch
              value={deep}
              onValueChange={setDeep}
              trackColor={{ false: colors.surfaceTertiary, true: colors.brandTertiary }}
              thumbColor={deep ? colors.brand : colors.onSurfaceSecondary}
              testID="steam-deep"
            />
          </View>

          <NeonButton
            title={scanning ? "SCANNING…" : "SCAN LIBRARY"}
            onPress={runScan}
            loading={scanning}
            disabled={!canScan}
            style={{ marginTop: spacing.lg }}
            testID="steam-scan-btn"
          />
          <Text style={styles.helpTight}>
            The key is used for this request and is not stored.
          </Text>

          {error ? (
            <View style={styles.errorBox} testID="steam-error">
              <Ionicons name="warning" size={16} color={colors.error} />
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : null}
        </Card>

        {loadingCached ? (
          <ActivityIndicator color={colors.brand} style={{ marginTop: spacing.xl }} />
        ) : null}

        {scan ? (
          <>
            <View style={styles.summary}>
              <Text style={styles.summaryBig}>{hits.length}</Text>
              <Text style={styles.summaryText}>
                of {scan.total_games} games can run a dedicated server
              </Text>
              {scan.unmatched ? (
                <Text style={styles.helpTight}>
                  {scan.unmatched} had no dedicated-server signal
                  {scan.deep ? "" : " — turn on deep scan to probe them"}
                </Text>
              ) : null}
            </View>

            {hits.map((g) => (
              <Card key={g.appid} style={styles.gameCard}>
                <View style={styles.gameRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.gameName}>{g.name}</Text>
                    <HostLine g={g} />
                  </View>
                  <View style={styles.playtime}>
                    <Text style={styles.playtimeText}>{hours(g.playtime_min)}</Text>
                  </View>
                </View>
              </Card>
            ))}

            {hits.length === 0 ? (
              <Text style={styles.empty}>
                No games in this library matched a dedicated server.
              </Text>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingHorizontal: spacing.lg, paddingBottom: spacing.md,
  },
  cardTitle: {
    fontFamily: fonts.displayBold, fontSize: fontSize.lg, color: colors.onSurface,
    letterSpacing: 1, marginBottom: spacing.sm,
  },
  help: {
    fontFamily: fonts.body, fontSize: fontSize.sm, color: colors.onSurfaceSecondary,
    lineHeight: 18, marginBottom: spacing.sm,
  },
  helpTight: {
    fontFamily: fonts.body, fontSize: 11, color: colors.onSurfaceSecondary,
    marginTop: spacing.xs, lineHeight: 15,
  },
  link: {
    fontFamily: fonts.monoMedium, fontSize: fontSize.sm, color: colors.brand,
    marginBottom: spacing.sm,
  },
  label: {
    fontFamily: fonts.monoMedium, fontSize: 10, color: colors.onSurfaceSecondary,
    letterSpacing: 1, marginTop: spacing.md, marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.surfaceTertiary, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    color: colors.onSurface, fontFamily: fonts.mono, fontSize: fontSize.base,
  },
  switchRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.lg,
  },
  rowLabel: { fontFamily: fonts.bodyMedium, fontSize: fontSize.base, color: colors.onSurface },
  errorBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.md,
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.error, backgroundColor: "rgba(255,42,42,0.08)",
  },
  errorText: { flex: 1, fontFamily: fonts.body, fontSize: fontSize.sm, color: colors.error },
  summary: { alignItems: "center", marginTop: spacing.xl, marginBottom: spacing.md },
  summaryBig: {
    fontFamily: fonts.displayBold, fontSize: 56, color: colors.brand, lineHeight: 60,
  },
  summaryText: {
    fontFamily: fonts.body, fontSize: fontSize.base, color: colors.onSurfaceSecondary,
  },
  gameCard: { marginBottom: spacing.sm },
  gameRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  gameName: { fontFamily: fonts.bodyMedium, fontSize: fontSize.base, color: colors.onSurface },
  how: {
    fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2,
  },
  playtime: {
    paddingHorizontal: spacing.sm, paddingVertical: spacing.xs,
    borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary,
  },
  playtimeText: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceTertiary },
  empty: {
    fontFamily: fonts.body, fontSize: fontSize.sm, color: colors.onSurfaceSecondary,
    textAlign: "center", marginTop: spacing.xl,
  },
});
