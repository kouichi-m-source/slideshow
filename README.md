# image-slideshow

<img src="assets/icon.png" width="96" align="right" alt="icon">

画像とGIFアニメーションを、自由なサイズのウィンドウで再生するスライドショーアプリです(Windows)。

## 主な機能

- 全画面ではなく、サイズ変更できるウィンドウで再生
- 選んだフォルダのサブフォルダまで含めて読み込み。再生中に別のフォルダ・ファイルを追加可能
- 自動送り(間隔は1〜60秒、または任意の秒数)
- 並び順: ファイル名順 / 更新日順 / ランダム(既定はランダム)
- 画像送り・戻り、ファイル削除(ゴミ箱へ移動)、名前変更、他のプログラムで開く
- 対応形式: jpg / jpeg / png / gif / bmp / webp

## 使い方

### exeで使う(おすすめ)

[Releases](../../releases) から `image-slideshow.exe` をダウンロードして実行します。

### Pythonで動かす

```
pip install -r requirements.txt
python image-slideshow.pyw
```

## 操作

| 操作 | 内容 |
|---|---|
| ← / マウスホイール上 | 前の画像 |
| → / マウスホイール下 | 次の画像 |
| Space | 自動送りの開始・停止 |
| Delete | ゴミ箱へ削除 |
| F2 | 名前変更 |
| Enter | 他のプログラムで開く |

フォルダやファイルの追加、再生リストのリセット、自動送りの間隔、並び順は「☰ メニュー」から操作します。

## exeの作り方(開発者向け)

`V1.0.0` のような `V` で始まるタグをpushすると、GitHub Actionsが
PyInstallerで `image-slideshow.exe` をビルドし、そのタグのリリースに自動で添付します。
手動で試すときは、Actionsタブの「Build and release exe」から実行すると、
ビルド結果をartifactとしてダウンロードできます。

## ライセンス

MIT License
