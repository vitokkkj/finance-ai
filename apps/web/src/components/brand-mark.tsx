import Image from "next/image";

type BrandMarkProps = {
  className?: string;
  size?: number;
};

export function BrandMark({ className = "assistant-brand-mark", size = 38 }: BrandMarkProps) {
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={className}
      height={size}
      src="/sophia-logo-mark.svg"
      unoptimized
      width={size}
    />
  );
}
