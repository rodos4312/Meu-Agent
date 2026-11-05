package io.meuagent.preview;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class SavedMeuConnection {
    private static final String KEY = "meu.android.pairing";
    private static final String SAVED = "paired-device";
    private static final String SESSION = "last-session";
    private final SharedPreferences preferences;

    SavedMeuConnection(Context context) {
        preferences = context.getSharedPreferences("meu-mobile", Context.MODE_PRIVATE);
    }

    boolean exists() {
        return preferences.contains(SAVED);
    }

    String lastSession() {
        return preferences.getString(SESSION, "");
    }

    void rememberSession(String id) {
        preferences.edit().putString(SESSION, id).apply();
    }

    void forget() {
        preferences.edit().remove(SAVED).remove(SESSION).apply();
    }

    void save(String code) throws GeneralSecurityException, IOException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key(true));
        Base64.Encoder encoder = Base64.getEncoder();
        String envelope = encoder.encodeToString(cipher.getIV()) + "."
                + encoder.encodeToString(cipher.doFinal(code.getBytes(StandardCharsets.UTF_8)));
        if (!preferences.edit().putString(SAVED, envelope).remove(SESSION).commit()) {
            throw new IOException("Could not save pairing");
        }
    }

    MeuPairing load() throws GeneralSecurityException, IOException {
        String envelope = preferences.getString(SAVED, "");
        String[] parts = envelope.split("\\.", -1);
        if (parts.length != 2) throw new GeneralSecurityException("Invalid saved pairing");
        Base64.Decoder decoder = Base64.getDecoder();
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, decoder.decode(parts[0])));
        return MeuPairing.parseSaved(new String(cipher.doFinal(decoder.decode(parts[1])), StandardCharsets.UTF_8));
    }

    private SecretKey key(boolean create) throws GeneralSecurityException, IOException {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        SecretKey existing = (SecretKey) store.getKey(KEY, null);
        if (existing != null) return existing;
        if (!create) throw new GeneralSecurityException("Missing saved pairing key");
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build());
        return generator.generateKey();
    }
}
