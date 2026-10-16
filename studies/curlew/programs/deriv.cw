-- Symbolic differentiation and simplification, after Gabriel's DERIV:
-- an algebraic data type, pattern matching and a lot of allocation.

data Expr = Num Int | Var Char | Add Expr Expr | Mul Expr Expr | Pow Expr Int
  deriving (Eq, Show)

d :: Char -> Expr -> Expr
d _ (Num _) = Num 0
d x (Var y) = if x == y then Num 1 else Num 0
d x (Add a b) = Add (d x a) (d x b)
d x (Mul a b) = Add (Mul (d x a) b) (Mul a (d x b))
d x (Pow a n) = Mul (Mul (Num n) (Pow a (n - 1))) (d x a)

simp :: Expr -> Expr
simp (Add a b) = case (simp a, simp b) of
  (Num 0, e) -> e
  (e, Num 0) -> e
  (Num m, Num n) -> Num (m + n)
  (e, f) -> Add e f
simp (Mul a b) = case (simp a, simp b) of
  (Num 0, _) -> Num 0
  (_, Num 0) -> Num 0
  (Num 1, e) -> e
  (e, Num 1) -> e
  (Num m, Num n) -> Num (m * n)
  (e, f) -> Mul e f
simp (Pow a 1) = simp a
simp (Pow a 0) = Num 1
simp (Pow a n) = Pow (simp a) n
simp e = e

size :: Expr -> Int
size (Add a b) = 1 + size a + size b
size (Mul a b) = 1 + size a + size b
size (Pow a _) = 1 + size a
size _ = 1

eval :: Int -> Expr -> Int
eval _ (Num n) = n
eval v (Var _) = v
eval v (Add a b) = eval v a + eval v b
eval v (Mul a b) = eval v a * eval v b
eval v (Pow a n) = eval v a ^ n

poly :: Expr
poly = Add (Add (Mul (Num 3) (Pow (Var 'x') 2)) (Mul (Num 2) (Var 'x'))) (Num 5)

main input = unlines
  [ "f    = " ++ show poly
  , "f'   = " ++ show (simp (d 'x' poly))
  , "f''  = " ++ show (simp (d 'x' (simp (d 'x' poly))))
  , "sizes of the first 6 derivatives, unsimplified: " ++ show (map size (take 6 (iterate (d 'x') big)))
  , "simplified: " ++ show (map (size . simp) (take 6 (iterate (simp . d 'x') big)))
  , "values at 2: " ++ show (map (eval 2) (take 6 (iterate (simp . d 'x') big)))
  ]
  where big = Mul (Pow (Add (Var 'x') (Num 1)) 6) (Add (Mul (Var 'x') (Var 'x')) (Num 3))
