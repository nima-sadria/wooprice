import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

interface DirectionContextValue {
  language: string
  direction: 'ltr' | 'rtl'
  setLanguage: (lang: string) => void
  setDirection: (dir: 'ltr' | 'rtl') => void
}

const DirectionContext = createContext<DirectionContextValue | null>(null)

const LANG_KEY = 'wp_lang'
const DIR_KEY = 'wp_dir'

export function DirectionProvider({ children }: { children: ReactNode }) {
  const [language, setLangState] = useState<string>('en')
  const [direction, setDirState] = useState<'ltr' | 'rtl'>('ltr')

  useEffect(() => {
    const savedLang = localStorage.getItem(LANG_KEY)
    const savedDir = localStorage.getItem(DIR_KEY) as 'ltr' | 'rtl' | null
    if (savedLang) {
      setLangState(savedLang)
      document.documentElement.lang = savedLang
    }
    if (savedDir === 'ltr' || savedDir === 'rtl') {
      setDirState(savedDir)
      document.documentElement.dir = savedDir
    }
  }, [])

  const setLanguage = useCallback((lang: string) => {
    setLangState(lang)
    document.documentElement.lang = lang
    localStorage.setItem(LANG_KEY, lang)
  }, [])

  const setDirection = useCallback((dir: 'ltr' | 'rtl') => {
    setDirState(dir)
    document.documentElement.dir = dir
    localStorage.setItem(DIR_KEY, dir)
  }, [])

  return (
    <DirectionContext.Provider value={{ language, direction, setLanguage, setDirection }}>
      {children}
    </DirectionContext.Provider>
  )
}

export function useDirection() {
  const ctx = useContext(DirectionContext)
  if (!ctx) throw new Error('useDirection must be used inside DirectionProvider')
  return ctx
}
