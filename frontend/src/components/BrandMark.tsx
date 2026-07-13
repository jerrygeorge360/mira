interface BrandMarkProps {
  className?: string;
  size?: number;
  title?: string;
}

export default function BrandMark({ className, size = 24, title }: BrandMarkProps) {
  return (
    <svg
      aria-hidden={title ? undefined : true}
      aria-label={title}
      className={className}
      height={size}
      role={title ? 'img' : undefined}
      viewBox="0 0 64 64"
      width={size}
    >
      <path
        d="M32 9C28 20 20 28 9 32c11 4 19 12 23 23 4-11 12-19 23-23C44 28 36 20 32 9Z"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="5"
      />
      <circle cx="32" cy="8" fill="currentColor" r="5" />
      <circle cx="56" cy="32" fill="currentColor" r="5" />
      <circle cx="32" cy="56" fill="currentColor" r="5" />
      <circle cx="8" cy="32" fill="currentColor" r="5" />
      <path
        d="M32 22c1.7 5.2 4.8 8.3 10 10-5.2 1.7-8.3 4.8-10 10-1.7-5.2-4.8-8.3-10-10 5.2-1.7 8.3-4.8 10-10Z"
        fill="var(--accent)"
      />
    </svg>
  );
}
