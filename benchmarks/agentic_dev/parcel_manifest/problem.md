# Parcel manifest の修正

`src/parcel_manifest/` に、複数行の発送データから送料明細を作る既存コードがあります。関連ファイルを調べ、公開関数 `parcel_manifest.build_manifest(rows)` を次の仕様に合わせて修正してください。

- `rows` は受付順に並ぶ辞書のリストです。各行は `order_id`（空でない文字列）、`zone`（前後に空白があり得る A/B/C の大小文字）、`weight_g`（1以上の整数）、`quantity`（1以上の整数）を持ちます。入力の形式は正しく、同じ注文IDの zone は正規化後に一致します。
- 注文IDは大文字小文字を区別し、その文字列を変更しません。同じIDの行は離れていても1件にまとめ、最初に現れた順で返します。重量は全行の `weight_g * quantity` を合計します。
- zone は前後の空白を除去して大文字にします。送料は**注文の合計重量**をkg単位で切り上げて計算します。A は400円/kg、B は600円/kg、C は900円/kgです。合計重量が2000gを**超える**注文だけ、さらに250円を加えます。
- 戻り値は `{"entries": [{"order_id": ..., "zone": ..., "weight_g": ..., "fee_yen": ...}, ...], "grand_total_yen": ...}` です。空入力なら空リストと0を返します。
- 入力の辞書・リストは変更せず、標準ライブラリだけを使ってください。公開テストは `python -m pytest -q public_tests -p no:cacheprovider` で実行できます。
