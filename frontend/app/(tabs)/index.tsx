import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  Pressable,
  ActivityIndicator,
  Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { useFocusEffect } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { api, Server } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/theme/theme";
import { ScreenTitle } from "@/src/components/common";
import ServerCard from "@/src/components/ServerCard";

export default function Dashboard() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [servers, setServers] = useState<Server[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get<Server[]>("/api/servers");
      setServers(data);
    } catch {
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      const data = await api.post<Server[]>("/api/servers/check-all");
      setServers(data);
    } catch {
    } finally {
      setRefreshing(false);
    }
  }, []);

  const total = servers.length;
  const down = servers.filter((s) => !s.last_status?.online).length;
  const allGood = total > 0 && down === 0;

  const summaryText =
    total === 0 ? "AWAITING NODES" : down === 0 ? "ALL SYSTEMS NOMINAL" : `${down} NODE${down > 1 ? "S" : ""} DOWN`;
  const summaryColor = total === 0 ? colors.onSurfaceSecondary : allGood ? colors.success : colors.error;

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <ScreenTitle eyebrow="COMMAND CENTER" title="Server Grid" />
        <View style={styles.summaryRow}>
          <View style={[styles.dot, { backgroundColor: summaryColor, shadowColor: summaryColor }]} />
          <Text style={[styles.summaryText, { color: summaryColor }]}>{summaryText}</Text>
          {total > 0 && (
            <Text style={styles.summaryCount}>
              {" "}· {total - down}/{total} ONLINE
            </Text>
          )}
        </View>
      </View>

      {loading ? (
        <View style={styles.centerFill}>
          <ActivityIndicator color={colors.brand} />
        </View>
      ) : total === 0 ? (
        <View style={styles.centerFill} testID="empty-state">
          <Ionicons name="server-outline" size={64} color={colors.surfaceTertiary} />
          <Text style={styles.emptyTitle}>NO NODES CONNECTED</Text>
          <Text style={styles.emptySub}>Add your first Webmin server to begin monitoring.</Text>
          <Pressable style={styles.emptyBtn} onPress={() => router.push("/server/add")} testID="empty-add-button">
            <Ionicons name="add" size={18} color={colors.onBrand} />
            <Text style={styles.emptyBtnText}>INITIALIZE SERVER</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={servers}
          keyExtractor={(s) => s.id}
          numColumns={2}
          columnWrapperStyle={{ gap: spacing.md }}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + 100, gap: spacing.md }}
          renderItem={({ item }) => (
            <ServerCard server={item} onPress={() => router.push(`/server/${item.id}`)} />
          )}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.brand} colors={[colors.brand]} />
          }
        />
      )}

      {total > 0 && (
        <Pressable
          testID="add-server-fab"
          onPress={() => {
            if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            router.push("/server/add");
          }}
          style={[styles.fab, { bottom: insets.bottom + spacing.lg }]}
        >
          <Ionicons name="add" size={28} color={colors.onBrand} />
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, backgroundColor: colors.surface },
  summaryRow: { flexDirection: "row", alignItems: "center", marginTop: spacing.md },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: spacing.sm, shadowOpacity: 0.9, shadowRadius: 5, shadowOffset: { width: 0, height: 0 } },
  summaryText: { fontFamily: fonts.monoMedium, fontSize: 12, letterSpacing: 1.5 },
  summaryCount: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurfaceSecondary },
  centerFill: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, letterSpacing: 1.5, marginTop: spacing.lg },
  emptySub: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center", marginTop: spacing.sm },
  emptyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    marginTop: spacing.xl,
  },
  emptyBtnText: { fontFamily: fonts.displayBold, fontSize: 14, color: colors.onBrand, letterSpacing: 1 },
  fab: {
    position: "absolute",
    right: spacing.lg,
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: colors.brand,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: colors.brand,
    shadowOpacity: 0.6,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
});
