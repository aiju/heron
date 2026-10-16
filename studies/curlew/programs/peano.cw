-- Peano arithmetic, after nofib's exp3_8: natural numbers as Z and S,
-- with addition, multiplication and powers defined by recursion, lazily.
-- 3^8 is a chain of 6561 S's, and every step of it allocates.

data Nat = Z | S Nat

plus :: Nat -> Nat -> Nat
plus Z y = y
plus (S x) y = S (plus x y)

times :: Nat -> Nat -> Nat
times Z _ = Z
times (S x) y = plus y (times x y)

power :: Nat -> Nat -> Nat
power _ Z = S Z
power x (S y) = times x (power x y)

fromInt :: Int -> Nat
fromInt 0 = Z
fromInt n = S (fromInt (n - 1))

toInt :: Nat -> Int
toInt n = go n 0 where go Z acc = acc
                       go (S m) acc = go m (acc + 1)

main input = "3^8 = " ++ show (toInt (power (fromInt 3) (fromInt 8))) ++ "\n"
  ++ "2^12 = " ++ show (toInt (power (fromInt 2) (fromInt 12))) ++ "\n"
