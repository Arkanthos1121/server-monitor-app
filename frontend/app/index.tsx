import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet, Text } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { colors, fonts } from "@/src/theme/theme";

export default function Index() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (user) router.replace("/(tabs)");
    else router.replace("/login");
  }, [user, loading, router]);

  return (
    <View style={styles.container} testID="splash-loading">
      <Text style={styles.brand}>WEBMIN<Text style={{ color: colors.brand }}>PULSE</Text></Text>
      <ActivityIndicator color={colors.brand} style={{ marginTop: 20 }} />
      <Text style={styles.sub}>AUTHENTICATING...</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  brand: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, letterSpacing: 2 },
  sub: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 12, letterSpacing: 3 },
});
