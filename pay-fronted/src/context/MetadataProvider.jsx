import { useMetadata } from "@/hooks/useMetadata"
import { MetadataContext } from "@/context/MetadataContext"

export function MetadataProvider({ children }) {
  const metadata = useMetadata()
  return <MetadataContext.Provider value={metadata}>{children}</MetadataContext.Provider>
}
