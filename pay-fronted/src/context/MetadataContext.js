import { createContext, useContext } from "react"

// 链/币基础元数据 Context：全局静态字典，避免穿过 PaymentStepper 向多个子组件 props drilling。
// 仅放 context 对象与读取 hook（无组件导出），Provider 组件拆到 MetadataProvider.jsx，
// 以满足 react-refresh「单文件只导出组件」的约束。
export const MetadataContext = createContext(null)

export function useMetadataContext() {
  const ctx = useContext(MetadataContext)
  if (!ctx) {
    throw new Error("useMetadataContext 必须在 MetadataProvider 内使用")
  }
  return ctx
}
