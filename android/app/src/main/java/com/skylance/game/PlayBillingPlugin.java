package com.skylance.game;

import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingFlowParams;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.ConsumeParams;
import com.android.billingclient.api.PendingPurchasesParams;
import com.android.billingclient.api.ProductDetails;
import com.android.billingclient.api.Purchase;
import com.android.billingclient.api.QueryProductDetailsParams;
import com.android.billingclient.api.QueryPurchasesParams;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONException;

/**
 * Google Play Billing for one-time gem packs.
 * The game never grants gems from this plugin's word alone: every purchase token is sent to the
 * server, which checks it with Google before the game adds gems and asks this plugin to consume it.
 */
@CapacitorPlugin(name = "PlayBilling")
public class PlayBillingPlugin extends Plugin {
    private BillingClient client;
    private final Map<String, ProductDetails> details = new HashMap<>();
    private final List<Runnable> waiting = new ArrayList<>();
    private boolean connecting = false;

    @Override
    public void load() {
        client = BillingClient.newBuilder(getContext())
            .setListener((result, purchases) -> {
                JSObject ev = new JSObject();
                ev.put("code", result.getResponseCode());
                ev.put("purchases", toJs(purchases));
                notifyListeners("purchasesUpdated", ev, true);
            })
            .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
            .enableAutoServiceReconnection()
            .build();
    }

    @Override
    protected void handleOnDestroy() {
        if (client != null) client.endConnection();
    }

    /** Runs the task once the billing service is connected, or fails the call. */
    private void ready(PluginCall call, Runnable task) {
        if (client.isReady()) { task.run(); return; }
        synchronized (waiting) {
            waiting.add(() -> { if (client.isReady()) task.run(); else call.reject("billing_unavailable"); });
            if (connecting) return;
            connecting = true;
        }
        client.startConnection(new BillingClientStateListener() {
            @Override
            public void onBillingSetupFinished(BillingResult r) { flush(); }

            @Override
            public void onBillingServiceDisconnected() { flush(); }
        });
    }

    private void flush() {
        List<Runnable> run;
        synchronized (waiting) { run = new ArrayList<>(waiting); waiting.clear(); connecting = false; }
        for (Runnable r : run) r.run();
    }

    private static JSArray toJs(List<Purchase> purchases) {
        JSArray arr = new JSArray();
        if (purchases == null) return arr;
        for (Purchase p : purchases) {
            JSObject o = new JSObject();
            o.put("token", p.getPurchaseToken());
            o.put("orderId", p.getOrderId());
            o.put("state", p.getPurchaseState() == Purchase.PurchaseState.PURCHASED ? "purchased" : p.getPurchaseState() == Purchase.PurchaseState.PENDING ? "pending" : "unknown");
            o.put("quantity", p.getQuantity());
            o.put("products", new JSArray(p.getProducts()));
            arr.put(o);
        }
        return arr;
    }

    @PluginMethod
    public void getProducts(PluginCall call) {
        List<String> ids;
        try { ids = call.getArray("ids").toList(); } catch (JSONException | NullPointerException e) { call.reject("ids required"); return; }
        ready(call, () -> {
            List<QueryProductDetailsParams.Product> list = new ArrayList<>();
            for (String id : ids) list.add(QueryProductDetailsParams.Product.newBuilder().setProductId(id).setProductType(BillingClient.ProductType.INAPP).build());
            client.queryProductDetailsAsync(QueryProductDetailsParams.newBuilder().setProductList(list).build(), (r, res) -> {
                if (r.getResponseCode() != BillingClient.BillingResponseCode.OK || res == null) { call.reject("query_failed", String.valueOf(r.getResponseCode())); return; }
                JSArray out = new JSArray();
                for (ProductDetails d : res.getProductDetailsList()) {
                    ProductDetails.OneTimePurchaseOfferDetails offer = d.getOneTimePurchaseOfferDetails();
                    if (offer == null) continue;
                    details.put(d.getProductId(), d);
                    JSObject o = new JSObject();
                    o.put("id", d.getProductId());
                    o.put("title", d.getName());
                    o.put("price", offer.getFormattedPrice());
                    o.put("micros", offer.getPriceAmountMicros());
                    o.put("currency", offer.getPriceCurrencyCode());
                    out.put(o);
                }
                JSObject ret = new JSObject();
                ret.put("products", out);
                call.resolve(ret);
            });
        });
    }

    @PluginMethod
    public void purchase(PluginCall call) {
        String id = call.getString("id"), account = call.getString("accountId");
        ProductDetails d = id == null ? null : details.get(id);
        if (d == null) { call.reject("unknown_product"); return; }
        ready(call, () -> getActivity().runOnUiThread(() -> {
            BillingFlowParams.ProductDetailsParams pp = BillingFlowParams.ProductDetailsParams.newBuilder().setProductDetails(d).build();
            BillingFlowParams.Builder b = BillingFlowParams.newBuilder().setProductDetailsParamsList(java.util.Collections.singletonList(pp));
            if (account != null) b.setObfuscatedAccountId(account);
            BillingResult r = client.launchBillingFlow(getActivity(), b.build());
            JSObject ret = new JSObject();
            ret.put("code", r.getResponseCode());
            call.resolve(ret);
        }));
    }

    /** Unconsumed purchases: used at launch to finish any purchase interrupted by a crash or a pending payment. */
    @PluginMethod
    public void queryPurchases(PluginCall call) {
        ready(call, () -> client.queryPurchasesAsync(QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.INAPP).build(), (r, list) -> {
            if (r.getResponseCode() != BillingClient.BillingResponseCode.OK) { call.reject("query_failed", String.valueOf(r.getResponseCode())); return; }
            JSObject ret = new JSObject();
            ret.put("purchases", toJs(list));
            call.resolve(ret);
        }));
    }

    @PluginMethod
    public void consume(PluginCall call) {
        String token = call.getString("token");
        if (token == null) { call.reject("token required"); return; }
        ready(call, () -> client.consumeAsync(ConsumeParams.newBuilder().setPurchaseToken(token).build(), (r, t) -> {
            JSObject ret = new JSObject();
            ret.put("code", r.getResponseCode());
            call.resolve(ret);
        }));
    }
}
