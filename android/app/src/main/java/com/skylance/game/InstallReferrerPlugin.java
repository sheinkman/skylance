package com.skylance.game;

import android.provider.Settings;
import com.android.installreferrer.api.InstallReferrerClient;
import com.android.installreferrer.api.InstallReferrerStateListener;
import com.android.installreferrer.api.ReferrerDetails;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Reads the Google Play install referrer once, so the game can credit the friend who invited this player.
 * Also returns this app's Android ID (unique per app and device). The game hashes it before it leaves the
 * phone and uses it only to stop one phone claiming many invite bonuses; it is not read for players under 13.
 */
@CapacitorPlugin(name = "InstallReferrer")
public class InstallReferrerPlugin extends Plugin {
    @PluginMethod
    public void deviceId(PluginCall call) {
        JSObject ret = new JSObject();
        String id = Settings.Secure.getString(getContext().getContentResolver(), Settings.Secure.ANDROID_ID);
        ret.put("id", id == null ? "" : id);
        call.resolve(ret);
    }

    @PluginMethod
    public void get(final PluginCall call) {
        final InstallReferrerClient client = InstallReferrerClient.newBuilder(getContext()).build();
        try {
            client.startConnection(new InstallReferrerStateListener() {
                private boolean done = false;

                @Override
                public void onInstallReferrerSetupFinished(int code) {
                    if (done) return;
                    done = true;
                    JSObject ret = new JSObject();
                    ret.put("referrer", "");
                    if (code == InstallReferrerClient.InstallReferrerResponse.OK) {
                        try {
                            ReferrerDetails d = client.getInstallReferrer();
                            ret.put("referrer", d.getInstallReferrer());
                        } catch (Exception ignored) { }
                    }
                    try { client.endConnection(); } catch (Exception ignored) { }
                    call.resolve(ret);
                }

                @Override
                public void onInstallReferrerServiceDisconnected() {
                    if (done) return;
                    done = true;
                    call.reject("disconnected");
                }
            });
        } catch (Exception e) {
            call.reject("unavailable");
        }
    }
}
