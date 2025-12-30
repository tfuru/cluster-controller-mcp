# cluster-controller-mcp

メタバースプラットフォーム cluster を MCP(Model Context Protocol) で制御するためのMCPサーバーです。  

## 概要


## 仮想環境の作成と有効化

```
# 1. 仮想環境を作成（フォルダ名は 'venv' が一般的です）
python3 -m venv venv

# 2. 仮想環境を有効化（アクティベート）
source venv/bin/activate

# (プロンプトの左側に (venv) と表示されれば成功です)
```

## 依存関係のインストール

```
pip install -r requirements.txt
```


## MCPサーバーの設定

設置場所の venv/bin/python のフルパスを指定してください。  
```
{
  "mcpServers": {
    "cluster-controller-mcp": {
      "command": "[pwd]/server/venv/bin/python",
      "args": [
        "[pwd]/server/main.py"
      ]
    }
  }
}
```