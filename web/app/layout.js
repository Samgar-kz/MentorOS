export const metadata = {
  title: "MentorOS",
  description: "AI tutor that never forgets",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui, -apple-system, sans-serif",
          maxWidth: 640,
          margin: "40px auto",
          padding: "0 16px",
          color: "#111",
        }}
      >
        {children}
      </body>
    </html>
  );
}
