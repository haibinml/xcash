import { useState, useEffect, useMemo, useCallback } from "react"
import { getMetadata } from "@/lib/api"

// metadata 缺失时的兜底显示名：按 - 拆分后首字母大写（如 "arbitrum-one" → "Arbitrum One"）
function titleCase(value) {
  return String(value)
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

// metadata 未就绪或链不在表中时，按关键字兜底判定测试网，避免把测试网误标为主网
const TESTNET_KEYWORDS = [
  "sepolia", "nile", "anvil", "testnet",
  "goerli", "holesky", "devnet", "shasta", "amoy", "fuji",
]

function fallbackIsTestnet(code) {
  const lower = String(code).toLowerCase()
  return TESTNET_KEYWORDS.some((kw) => lower.includes(kw))
}

/**
 * 链/币基础元数据 Hook
 * 加载时拉取一次后端单一来源字典，按 code/symbol 建表供 O(1) 查询。
 * 拉取失败不阻塞支付流程：getChain/getCrypto 退化为本地兜底（名首字母大写、无图标）。
 */
export function useMetadata() {
  // null 表示尚未加载完成；加载完成（含失败降级）后为 Map，getter 据此决定走表还是兜底。
  const [chains, setChains] = useState(null)
  const [cryptos, setCryptos] = useState(null)

  useEffect(() => {
    let cancelled = false
    getMetadata()
      .then((data) => {
        if (cancelled) return
        setChains(new Map((data.chains ?? []).map((item) => [item.code, item])))
        setCryptos(new Map((data.cryptos ?? []).map((item) => [item.symbol, item])))
      })
      .catch(() => {
        // 失败静默降级：置空 Map 让 getter 走兜底。错误已在 api 层 console.error。
        if (cancelled) return
        setChains(new Map())
        setCryptos(new Map())
      })
    return () => {
      cancelled = true
    }
  }, [])

  const getChain = useCallback(
    (code) => {
      const meta = chains?.get(code)
      if (meta) {
        return { name: meta.name, icon: meta.icon, isTestnet: Boolean(meta.is_testnet) }
      }
      return {
        name: code ? titleCase(code) : "",
        icon: "",
        isTestnet: code ? fallbackIsTestnet(code) : false,
      }
    },
    [chains]
  )

  const getCrypto = useCallback(
    (symbol) => {
      const meta = cryptos?.get(symbol)
      if (meta) {
        return { name: meta.name, icon: meta.icon }
      }
      return { name: symbol ? String(symbol).toUpperCase() : "", icon: "" }
    },
    [cryptos]
  )

  return useMemo(() => ({ getChain, getCrypto }), [getChain, getCrypto])
}
