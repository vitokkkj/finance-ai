export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  mfa_required: boolean;
  mfa_enrolled: boolean;
  avatar_url?: string | null;
};
