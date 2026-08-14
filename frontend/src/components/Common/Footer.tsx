export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <div className="flex items-center justify-center">
        <p className="text-sm text-muted-foreground">
          行伴 · AI 旅行助手 © {currentYear}
        </p>
      </div>
    </footer>
  )
}
